"""Restore attempt 326's original relay bytes and resume the existing audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SELF = str(Path(__file__).resolve())
REV = ROOT / 'execution-revisions/completion-r30'
PY = '/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_bytes(relay_path, completion_path, recovery_path):
    """Require the historically bound relay, not a synthesized process result."""
    raw = relay_path.read_bytes()
    relay, completion, recovery = json.loads(raw), read(completion_path), read(recovery_path)
    if hashlib.sha256(raw).hexdigest() != recovery['original_relay_sha256']:
        raise ValueError('original relay SHA differs from recovery receipt')
    if digest(completion_path) != recovery['completion_sha256']:
        raise ValueError('historical completion SHA changed')
    if relay != completion['resources'] or relay['pid'] != completion['pid'] or relay['pid'] != 48636:
        raise ValueError('original process identity or resources differ')
    if relay['status'] != 'FINISHED' or relay['returncode'] != 0 or relay['stop_reason'] is not None:
        raise ValueError('original process did not finish successfully')
    if completion['attempt'] != 326 or completion['job']['job_id'] != 'm79-a-c2-b34-s1':
        raise ValueError('original job identity differs')
    return raw


def install():
    from scripts import prism_m79_completion_r29 as r29
    meta = read(REV / 'revision.json')
    if digest(Path(SELF)) != meta['adapter_sha256'] or digest(ROOT/'execution.json') != meta['execution_sha256']:
        raise ValueError('r30 identity drift')
    if digest(ROOT/'scripts/prism_m79_completion_r29.py') != meta['r29_sha256']:
        raise ValueError('r29 retained source drift')
    r29.install()
    r29.prior.SELF = SELF
    return r29.prior


def resume():
    import resource
    from scripts import prism_m79_completion_r24 as prior, prism_m79_completion_r21 as r21
    from training.prism_portable.common import write, lock
    import platform
    import psutil
    with lock(ROOT/'launch-control'):
        prior.no_writer(); r21.verify(); prior.verify()
        if REV.exists():
            raise ValueError('r30 already prepared; inspect before another attempt')
        status = read(ROOT/'pipeline/status.json')
        audit = read(ROOT/'pipeline/audit.completion.json')
        if status['state'] != 'STOPPED_REQUIRES_RECONCILIATION' or status['phase'] != 'AUDIT' or audit['status'] != 'FAIL':
            raise ValueError('unexpected stage state')
        if read(ROOT/'pipeline/train.completion.json')['status'] != 'PASS':
            raise ValueError('training not complete')
        log = ROOT/'pipeline/audit-19.log'
        if 'FileNotFoundError' not in log.read_text() or '/attempts/326/process-result.json' not in log.read_text():
            raise ValueError('unexpected audit failure')
        rows = read(ROOT/'pipeline/resources.json')
        if any(row['state']=='RUNNING' for row in rows):
            raise ValueError('live resource entry')
        if sum(prior.cpu(row) for row in rows if row['category']=='audit_transfer_control') >= 29990:
            raise ValueError('audit budget exhausted')
        directory = ROOT/'campaigns/a/attempts/326'
        relay = ROOT/'campaigns/a/control/relay/2bbf98659e9040ab94b32546c8f251d9.json'
        completion = directory/'completion.json'
        recovery = ROOT/'migration-r8/attempt326-recovery-receipt.json'
        raw = receipt_bytes(relay, completion, recovery)
        missing = sorted(p.name for p in (ROOT/'campaigns/a/attempts').iterdir()
                         if p.is_dir() and (p/'completion.json').exists() and not (p/'process-result.json').exists())
        if missing != ['326']:
            raise ValueError('missing process receipt inventory changed')
        saved = read(completion)
        for v in saved['files'].values():
            if digest(Path(v['path'])) != v['sha256']:
                raise ValueError('original game evidence SHA mismatch')
        immutable = [ROOT/'campaigns/a/run/HEAD.json', ROOT/'campaigns/a/launch-ledger/HEAD.json',
                     ROOT/'campaigns/a/cycle-20-export/weights.json', completion]
        before = {str(p):digest(p) for p in immutable}
        if before[str(immutable[2])] != 'ecb5d3a3e371c743f81bccdea48afbe2e4c3bf2a40d41121817895a20d60a17b':
            raise ValueError('fixed c20 SHA drift')
        REV.mkdir(parents=True)
        for name in ('status.json','audit.completion.json','resources.json'):
            shutil.copyfile(ROOT/'pipeline'/name, REV/('prior-'+name))
        with (directory/'process-result.json').open('xb') as stream:
            stream.write(raw)
        if digest(directory/'process-result.json') != digest(relay):
            raise ValueError('restored bytes mismatch')
        for path, sha in before.items():
            if digest(Path(path)) != sha:
                raise ValueError('immutable scientific evidence changed')
        failed = ROOT/'audits/a'
        if failed.exists():
            shutil.move(str(failed), str(REV/'retained-failed-audit'))
        meta = dict(adapter_sha256=digest(Path(SELF)), execution_sha256=digest(ROOT/'execution.json'),
                    r29_sha256=digest(ROOT/'scripts/prism_m79_completion_r29.py'),
                    original_relay_sha256=digest(relay), recovery_receipt_sha256=digest(recovery),
                    original_completion_sha256=digest(completion), immutable_before=before,
                    restored_process_result_sha256=digest(directory/'process-result.json'),
                    restoration='exact byte copy of historically SHA-bound original relay',
                    failure_log_sha256=digest(log), launch_limit=1, new_training_games=0,
                    scientific_change=False, observed_at=time.time())
        write(REV/'revision.json', meta)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rows.append(dict(category='audit_transfer_control',mode='r30_original_receipt_restoration',
                         state='FINISHED',cpu_seconds=usage.ru_utime+usage.ru_stime,
                         new_games=0, observed_at=time.time()))
        write(ROOT/'pipeline/resources.json', rows)
        with (REV/'supervisor.log').open('xb') as stream:
            p = subprocess.Popen([PY,'-B',SELF,'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,
                                 stdout=stream,stderr=stream,start_new_session=True)
        launch = dict(status='STARTED_R30_AUDIT_CONTINUATION',node=platform.node(),pid=p.pid,
                      create_time=psutil.Process(p.pid).create_time(),observed_at=time.time(),
                      adapter_sha256=meta['adapter_sha256'],restoration=meta['restoration'])
        write(REV/'launch.json', launch)
        return launch


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode'); parser.add_argument('--output')
    args = parser.parse_args()
    if args.mode == 'resume':
        result = resume()
    else:
        prior = install()
        result = prior.pipeline() if args.mode == 'pipeline' else prior.execute(args.mode,args.output)
    print(json.dumps(result),flush=True)
