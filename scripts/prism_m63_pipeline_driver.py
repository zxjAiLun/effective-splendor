"""Bounded M63 training -> audit -> fixed evaluation -> readable reports.

No retry or checkpoint selection. Runs in an owned 8GiB/200%/27h user unit;
audit children inherit its cgroup. Historical M62 driver remains untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CONFIG = 'benchmarks/m63-prism-beta-timed-building.config.json'


def require(ok, message):
    if not ok:
        raise ValueError('M63 pipeline: ' + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def save(path, value):
    from training.prism_portable.common import write
    write(path, value)


def completed_evaluation(completion, result):
    require(completion.get('status') == result.get('status') == 'COMPLETED_FIXED_BUILDING_EVALUATION', 'unexpected evaluation status')
    require(result.get('format') == 'm63-building-evaluation-result-v1' and isinstance(result.get('verdicts'), dict),
            'result schema/verdicts missing')
    require(completion.get('physical_games') == result.get('physical_games') == 10304 and
            result.get('development', {}).get('games') == 576 and
            result.get('acceptance', {}).get('games') == 9728, 'evaluation budget incomplete')
    require(completion.get('retry') == result.get('retries') == 0 and
            completion.get('formal_gates_analyzed_once') is True, 'evaluation retry/analysis contract drift')
    return result['verdicts']


def validate_resources(props, pid, contract):
    require(contract == {'memory_bytes':8*1024**3,'cpu_quota_percent':200,'wall_seconds':97200,
                         'automatic_retries':0,'audit_scope':'children inherit pipeline cgroup'}, 'pipeline contract drift')
    require(props.get('MainPID') == str(pid) and props.get('MemoryMax') == str(contract['memory_bytes'])
            and props.get('CPUQuotaPerSecUSec') == '2s' and
            props.get('RuntimeMaxUSec') in ('1d 3h','27h','97200000000'),
            'pipeline must run in 8GiB/200%/27h owned unit')


def run_pipeline(project, unit):
    project = Path(project).resolve()
    require(str(project) == '/home/ubuntu/splendor-ppo-m63', 'wrong root')
    sys.path.insert(0, str(project))
    from training.prism_portable.processes import systemctl, cgroup_accounting
    from training.prism_portable.common import package_identity, numerical_identity
    config = read(project / CONFIG)
    require(config['status'] == 'FROZEN_BEFORE_FIRST_GAME', 'config not frozen')
    require(package_identity() == config['runtime']['package_identity'] and
            numerical_identity() == config['runtime']['numerical_identity'], 'package identity drift')
    for name, digest in config['runtime']['source_hashes'].items():
        require(sha(project / name) == digest, 'source drift: ' + name)
    import markdown
    renderer=config['runtime']['html_renderer']
    require(markdown.__version__==renderer['version'] and Path(markdown.__file__).resolve().is_relative_to(
            Path(renderer['installation']).resolve()) and sha(project/'dependencies'/renderer['wheel_filename'])==
            renderer['wheel_sha256'],'isolated HTML renderer drift')
    require(unit.startswith('prism-m63-pipeline-') and unit.endswith('.service'), 'owned unit required')
    props = dict(line.split('=',1) for line in systemctl('show',unit,'--property=MainPID,MemoryMax,CPUQuotaPerSecUSec,RuntimeMaxUSec').stdout.splitlines() if '=' in line)
    validate_resources(props, os.getpid(), config['pipeline_resources'])
    receipt_path = project / 'pipeline-driver-completion.json'
    require(not receipt_path.exists() and not (project/'pipeline-driver-start.json').exists(), 'already launched; no restart')
    record={'format':'m63-pipeline-driver-completion-v1','status':'RUNNING','started_at':time.time(),
            'source_sha256':sha(__file__),'config_sha256':sha(project/CONFIG),'command':sys.argv,
            'resources':props,'automatic_retries':0,'steps':{}}
    save(project/'pipeline-driver-start.json',record)
    def command(label, argv, timeout):
        tick=time.monotonic()
        p=subprocess.run(argv,cwd=project,capture_output=True,text=True,timeout=timeout)
        record['steps'][label]={'argv':argv,'exit_code':p.returncode,'wall_seconds':time.monotonic()-tick,
                                'stdout':p.stdout,'stderr':p.stderr}
        save(project/'pipeline-driver-progress.json',record)
        require(p.returncode==0,label+' exited '+str(p.returncode))
    evaluation_unit = None
    try:
        deadline=time.monotonic()+17*3600
        final=project/'training-receipts/serial-final.json'
        while not final.exists():
            require(time.monotonic()<deadline,'training wait deadline exceeded')
            time.sleep(30)
        training=read(final)
        require(training['status']=='TRAINING_COMPLETED_PENDING_INDEPENDENT_AUDIT','training failed; stop without retry')
        record['steps']['training']={'final_path':str(final),'sha256':sha(final),'status':training['status']}
        python=sys.executable
        command('audit',[python,'-B','scripts/prism_building_audit_m63.py','--project',str(project)],7200)
        command('training_report',[python,'-B','scripts/prism_building_training_report_m63.py','--project',str(project)],7200)
        audit=project/'training-artifact-audit.json'
        require(read(audit)['status']=='PASS_TRAINING_ARTIFACT_AUDIT','audit binding failed')
        command('eval_prepare',[python,'-B','scripts/prism_building_evaluation_m63.py','prepare','--project',str(project),
                               '--config-sha256',sha(project/CONFIG),'--audit-receipt',str(audit)],300)
        execution=project/'evaluation/execution.json';digest=sha(execution)
        command('eval_verify',[python,'-B','scripts/prism_building_evaluation_m63.py','verify','--project',str(project),
                              '--execution-sha256',digest],300)
        evaluation_unit='prism-m63-evaluation-'+digest[:8]
        argv=['systemd-run','--user','--quiet','--unit='+evaluation_unit,'--property=MemoryMax=8589934592',
              '--property=CPUQuota=200%','--property=RuntimeMaxSec=28800','--working-directory='+str(project),
              python,'-B','scripts/prism_building_evaluation_m63.py','run','--project',str(project),'--execution-sha256',digest]
        command('eval_launch',argv,30)
        deadline=time.monotonic()+28830
        while True:
            state=dict(line.split('=',1) for line in systemctl('show',evaluation_unit+'.service',
                         '--property=ActiveState,SubState,MainPID,Result,ExecMainStatus',check=False).stdout.splitlines() if '=' in line)
            if state.get('ActiveState') in ('inactive','failed') and state.get('MainPID')=='0':
                break
            require(time.monotonic()<deadline,'evaluation deadline exceeded')
            time.sleep(30)
        require(state.get('Result')=='success' and state.get('ExecMainStatus')=='0','evaluation service failed')
        completion=project/'evaluation/completion.json';result=project/'evaluation/result.json'
        require(read(completion)['result_sha256']==sha(result),'completion/result hash drift')
        verdicts=completed_evaluation(read(completion),read(result))
        record['steps']['evaluation']={'unit':evaluation_unit,'state':state,'completion_sha256':sha(completion),
                                      'result_sha256':sha(result),'verdicts':verdicts}
        output=project/'docs/prism/m63-prism-beta-timed-building-evaluation.md'
        command('readable_report',[python,'-B','scripts/prism_building_report_m63.py','--work',str(project/'evaluation'),
                                   '--output',str(output)],300)
        output_html=output.with_suffix('.html')
        command('html_report',[python,'-B','scripts/prism_building_html_report_m63.py','--markdown',str(output),
                               '--result',str(result),'--output',str(output_html)],300)
        record.update(status='PASS_FULL_PIPELINE',verdicts=verdicts,report_sha256=sha(output),html_sha256=sha(output_html))
    except BaseException as exc:
        record.update(status='FAILED_STOPPED_NO_RETRY',error=type(exc).__name__+': '+str(exc))
        if evaluation_unit is not None:
            stop=systemctl('stop',evaluation_unit+'.service',check=False)
            record['evaluation_stop']={'unit':evaluation_unit+'.service','exit_code':stop.returncode}
        raise
    finally:
        record.update(finished_at=time.time(),total_wall_seconds=time.time()-record['started_at'],
                      observed_resources=cgroup_accounting(unit))
        save(receipt_path,record)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/home/ubuntu/splendor-ppo-m63'))
    parser.add_argument('--unit',required=True)
    args=parser.parse_args()
    run_pipeline(args.project,args.unit)
