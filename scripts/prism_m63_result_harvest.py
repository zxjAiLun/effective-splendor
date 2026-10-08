"""One bounded M63 result collection job; never starts, resumes or retries games.

Cloud services own the experiment. This local reader survives chat completion,
checks completion/source hashes, and brings the readable reports into the workspace.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ART = ROOT/'local-artifacts/prism/building-beta-m63'
CLOUD = '/home/ubuntu/splendor-ppo-m63'
PYTHON = '/home/ubuntu/splendor-ppo-m57/venv/bin/python'
REPORT = 'docs/prism/m63-prism-beta-timed-building-evaluation.md'
STATUS_PAGE = ROOT/'docs/prism/m63-beta-iteration-status.html'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text('utf-8'))
def save(path, value):
    from training.prism_portable.common import write
    write(path,value)


REMOTE = r'''import json,hashlib,subprocess
from pathlib import Path
root=Path('/home/ubuntu/splendor-ppo-m63');files={}
completion=root/'pipeline-driver-completion.json'
unit='prism-m63-pipeline-'+hashlib.sha256((root/'benchmarks/m63-prism-beta-timed-building.config.json').read_bytes()).hexdigest()[:8]+'.service'
service=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,MainPID,Result,ExecMainStatus'],capture_output=True,text=True,check=True).stdout
if completion.exists():
    names=['pipeline-driver-completion.json','training-receipts/serial-final.json','training-artifact-audit.json','training-evidence-manifest.json','evaluation/result.json','evaluation/execution.json','evaluation/completion.json','docs/prism/m63-prism-beta-timed-building-evaluation.md','docs/prism/m63-prism-beta-timed-building-evaluation.html']
    for stage in ('development','acceptance'):
        names += ['evaluation/'+stage+'/'+n+'.json' for n in ('plan','source-ledger','style-metrics','building-metrics','match-details')]
    for arm in ('control','beta'):
        c='campaigns/m63-'+arm+'-building-g0/'
        names += [c+'cycle-4-export/'+n for n in ('weights.json','weights.manifest.json')]
        names += [c+n for n in ('checkpoint-audit.json','parity-audit.json','training-audit.json','training-source-ledger.json','training-matches.md')]
    for n in names:
        p=root/n
        assert p.resolve().is_relative_to(root.resolve())
        if p.is_file(): files[n]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
    state=json.loads(completion.read_text())['status']
else: state='RUNNING'
print(json.dumps({'state':state,'service':service,'files':files}))
'''


def snapshot():
    proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','cloud1',PYTHON+' -B -'],
                        input=REMOTE,capture_output=True,text=True,timeout=60)
    if proc.returncode: raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def collect(snap):
    downloaded={}
    for name,desc in snap['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('unsafe evidence path')
        target=ART/'cloud-generated'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if sha(target)!=desc['sha256']: raise ValueError('refuse conflicting previous evidence: '+name)
        else:
            partial=target.with_suffix(target.suffix+'.download')
            subprocess.run(['scp','-q','cloud1:'+CLOUD+'/'+name,str(partial)],check=True,timeout=180)
            if sha(partial)!=desc['sha256']: raise ValueError('fetched hash mismatch: '+name)
            partial.replace(target)
        downloaded[name]=dict(local_path=str(target),**desc)
    save(ART/'result-fetch-receipt.json',{'status':'PASS_FETCHED_HASHES','new_games':0,
        'scope':'summaries, weights and ledgers; full raw replays/torch recovery payloads remain on cloud1',
        'files':downloaded,'pipeline_status':snap['state'],'source_sha256':sha(__file__)})
    return ART/'cloud-generated'


def readable_reports(base):
    from scripts import prism_building_report_m63 as report
    from scripts import prism_building_evaluation_m63 as evaluation
    from scripts import prism_building_html_report_m63 as html
    from scripts import prism_m63_pipeline_driver as driver
    result=read(base/'evaluation/result.json');completion=read(base/'evaluation/completion.json')
    pipeline=read(base/'pipeline-driver-completion.json')
    driver.completed_evaluation(completion,result)
    assert completion['result_sha256']==pipeline['steps']['evaluation']['result_sha256']==sha(base/'evaluation/result.json')
    assert result['config_sha256']==pipeline['config_sha256']==sha(ROOT/evaluation.CONFIG)
    report.validate_measurements(result)
    raw=base/REPORT
    assert sha(raw)==pipeline['report_sha256'] and sha(raw.with_suffix('.html'))==pipeline['html_sha256']
    text=raw.read_text('utf-8'); original_line=next(line for line in text.splitlines() if line.startswith('| 自身Main得分速度 |'))
    pairs=report.legacy.keyed_pairs(result['acceptance']);values=[]
    for model in evaluation.MODELS:
        metrics=[pairs[(model,op)]['candidate_metrics'] for op in evaluation.ANCHORS]
        points=math.fsum(m['mean_prestige']*m['games'] for m in metrics)
        mains=sum(m['total_main_actions'] for m in metrics)
        values.append(points/mains)
    a,b,c=values
    corrected=report.tables.table(['unused'],[['自身Main得分速度','VP/Main，模型本人；总VP/总Main',
        *map(report.fmt,values),report.change(a,b,False),report.change(b,c,False),report.change(a,c,False)]]).splitlines()[-1]
    # All frozen match tables and formal gates remain. This corrects one new descriptive ratio.
    text=text.replace(original_line,corrected,1)
    text += '\n## 本地可读汇总校验\n\n共同锚点的自身Main得分速度用三组总VP/总Main重算；其余共同锚点均值按等局数锚点合并。此修订只改变一行描述性比率，原完整云端Markdown/HTML和流水线SHA保留在ignored cloud-generated归档，所有十门与原结果不改。原报告SHA256 `'+sha(raw)+'`；本地汇总脚本SHA256 `'+sha(__file__)+'`。完整回放与恢复checkpoint仍在cloud1，未声称本地全量复审。\n'
    target=ROOT/REPORT
    assert not target.exists() and not target.with_suffix('.html').exists(),'refuse overwriting existing readable result'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
    html.main(target,base/'evaluation/result.json',target.with_suffix('.html'))
    tracked=ROOT/'benchmarks/m63-prism-beta-timed-building.result.json'
    assert not tracked.exists()
    tracked.write_bytes((base/'evaluation/result.json').read_bytes())
    receipt={'status':'PASS_HASHES_SCHEMA_GATES_AND_READABLE_TABLES','new_games':0,'verdicts':result['verdicts'],
        'result_sha256':sha(tracked),'report_sha256':sha(target),'html_sha256':sha(target.with_suffix('.html')),
        'formal_gate_analysis_rerun':False,'browser_visual_review':'NOT_RUN','ratio_correction':{'old_row':original_line,'new_row':corrected}}
    save(ART/'local-readable-closeout.json',receipt)
    milestone=ROOT/'docs/m63-prism-beta-timed-building.md';text=milestone.read_text('utf-8')
    text=text.replace('Status: IMPLEMENTED / FROZEN_BEFORE_FIRST_GAME / TRAINING_RUNNING；开发与独立验收 NOT_RUN。',
        'Status: FIXED_EVALUATION_COMPLETED / '+result['verdicts']['beta_acceptance']+'；未发布。')
    text+='\n## 固定执行完成补记\n\n实际pipeline PASS_FULL_PIPELINE；2,048训练和10,304固定评测全量完成，0重试。此处为机器合同结果与本地已抓取证据的hash/schema校验，浏览器目视复审NOT_RUN。最终判定 `'+result['verdicts']['beta_acceptance']+'`，产物审计、竞技门、风格门分别见[完整双方Markdown](prism/m63-prism-beta-timed-building-evaluation.md)与[HTML](prism/m63-prism-beta-timed-building-evaluation.html)。新候选仍未发布/部署/登记；失败门与不确定性保持。\n\n结果SHA `'+receipt['result_sha256']+'`；本地完整报告SHA `'+receipt['report_sha256']+'`。下一步只读复审结果与浏览器，不能自动扩赛/调门/加训。\n'
    milestone.write_text(text,encoding='utf-8')
    handoff=ROOT/'handoff.md';text=handoff.read_text('utf-8')
    marker='## Current Snapshot\n'
    text=text.replace(marker,marker+'\n### M63固定执行完成（自动抓取校验，待主代理目视复审）\n\n'+
        result['verdicts']['beta_acceptance']+'；2,048训练+576开发+9,728独立完成0重试，完整双方Markdown/HTML在`docs/prism/m63-prism-beta-timed-building-evaluation.{md,html}`。raw result字节原样放入本轮benchmark；完整回放/恢复checkpoint仍在cloud1。原门与失败不改，下一步主代理只读结果复审/浏览器校验。未发布/登记/部署/提交/push。\n',1)
    handoff.write_text(text,encoding='utf-8')
    STATUS_PAGE.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M63 固定评测完成</title><style>body{font:18px system-ui;max-width:960px;margin:60px auto;padding:24px;line-height:1.8}a{color:#087f71}</style><h1>M63 固定训练与评测完成</h1><p>Prism Beta v0.1.1 candidate：'+result['verdicts']['beta_acceptance']+'</p><p>两臂2,048训练局；576开发＋9,728独立验收局，0重试。候选尚未发布，浏览器目视复审待完成。</p><p><a href="m63-prism-beta-timed-building-evaluation.html">打开完整HTML：结论、门与双方详细对战表</a></p><p><a href="m63-prism-beta-timed-building-evaluation.md">完整Markdown</a></p></html>',encoding='utf-8')
    return receipt


def watch(hours):
    deadline=time.monotonic()+hours*3600
    save(ART/'local-harvest-status.json',{'state':'WAITING','pid':__import__('os').getpid(),'source_sha256':sha(__file__),'max_hours':hours,'new_games':0})
    while time.monotonic()<deadline:
        snap=snapshot()
        if snap['state']!='RUNNING':
            base=collect(snap)
            if snap['state']=='PASS_FULL_PIPELINE': receipt=readable_reports(base)
            else: receipt={'status':snap['state'],'scientific_evaluation':'INCOMPLETE','failure':read(base/'pipeline-driver-completion.json').get('error')}
            save(ART/'local-harvest-status.json',receipt);print(json.dumps(receipt),flush=True);return
        if 'ActiveState=failed' in snap['service'] or ('ActiveState=inactive' in snap['service'] and 'MainPID=0' in snap['service']):
            raise RuntimeError('pipeline exited without its final receipt: '+snap['service'])
        time.sleep(55)
    raise TimeoutError('bounded collection deadline; cloud experiment is not restarted or stopped')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hours',type=float,default=28)
    args=parser.parse_args()
    try: watch(args.hours)
    except BaseException as exc:
        save(ART/'local-harvest-status.json',{'state':'FAILED_LOCAL_COLLECTION','error':type(exc).__name__+': '+str(exc),'new_games':0})
        raise
