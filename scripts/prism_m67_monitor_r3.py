"""Read-only local R3 SSH observer with actual PID identity and ALL heartbeat.
No remote restart, retry, adjudication or task closure. Requires local machine online.
"""
from pathlib import Path
import datetime, os
import json
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write
from scripts.prism_m67_monitor import all_call, AGENT, TASK
OUT = ROOT / 'local-artifacts/prism/m67-alpha-repeat' / os.environ.get('M67_R3_OBSERVER_FOLDER', 'monitor-r3')
REMOTE = '/mnt/workspace/splendor-m67-alpha-repeat'
PROBE = r'''
from pathlib import Path
import psutil,json,time
r=Path('/mnt/workspace/splendor-m67-alpha-repeat');v=r/'continuation-r3'
launch=json.loads((v/'launch.json').read_text());state=json.loads((v/'status.json').read_text())
try:
 p=psutil.Process(launch['pid']);alive=p.is_running() and p.status()!=psutil.STATUS_ZOMBIE and abs(p.create_time()-launch['create_time'])<.01 and str(r/'scripts/prism_m67_eval_recovery_r3.py') in p.cmdline()
except psutil.Error:alive=False
stages={};total=0
for name in ['reference','a-common','a-direct','b-common','b-direct']:
 w=r/'evaluation'/name;path=w/'status.json'
 if not path.exists():continue
 s=json.loads(path.read_text());stages[name]={k:s.get(k) for k in ['state','completed_games','total_games','elapsed_wall_seconds','error']}
 total+=s.get('completed_games',0)
a=r/'evaluation/a-common-recovery-r3/status.json'
if a.exists():
 s=json.loads(a.read_text());stages['a-common-recovery-r3']={k:s.get(k) for k in ['state','completed_games','total_games','error']}
 total+=s['completed_games']-stages['a-common']['completed_games']
else:total+=74
print(json.dumps(dict(observed_at=time.time(),launch=launch,state=state,process_identity_matches=alive,stages=stages,completed_evaluations=total)))
'''


def probe():
    x = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'dsw', '/mnt/workspace/envs/splendor-arena-py312/bin/python', '-B', '-'], input=PROBE, capture_output=True, text=True, encoding='utf-8', timeout=40)
    if x.returncode: raise RuntimeError(x.stderr[-2000:])
    return json.loads(x.stdout)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'once-only.lock').open('x'): pass
    failures = 0
    while time.time() < 1791383966.021502 + 120:
        try:
            obs = probe(); failures = 0; write(OUT / 'latest-observation.json', obs)
            with (OUT / 'history.jsonl').open('a', encoding='utf-8') as stream: stream.write(json.dumps(obs, ensure_ascii=False) + '\n')
            state = obs['state']; running = obs['process_identity_matches'] and state['state'] == 'RUNNING'
            terminal = 'failed' if state['state'].startswith('FAILED') else 'paused'
            progress = '; '.join(f"{k}: {s['completed_games']}/{s['total_games']} {s['state']}" for k, s in obs['stages'].items())
            all_call('report-run', dict(agentId=AGENT, id='splendor:m67-repeat', projectId='splendor', taskId=TASK, nodeId='dsw',
                name='M67 R3 固定权重剩余greedy评测', kind='arena', pid=obs['launch']['pid'], executionId='m67-evaluation-r3-e614b1935e0f',
                state='running' if running else terminal if not obs['process_identity_matches'] else 'unknown', phase=state['phase'],
                progress=progress + '; retained safety failure/orphans, no fabricated outcome',
                sampledAt=datetime.datetime.fromtimestamp(obs['observed_at'], datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                metrics=dict(completed=obs['completed_evaluations'], total=110000)))
            if not running:
                write(OUT / 'completion.json', dict(status='OBSERVED_STOP_NO_RESTART', observation=obs)); return
        except Exception as error:
            failures += 1; write(OUT / 'error.json', dict(observed_at=time.time(), error=repr(error), consecutive_errors=failures))
            if failures >= 3:
                write(OUT / 'completion.json', dict(status='OBSERVER_FAILED_REMOTE_NOT_RESTARTED', error=repr(error))); return
        time.sleep(45)
    write(OUT / 'completion.json', dict(status='OBSERVER_DEADLINE_REACHED_REMOTE_NOT_RESTARTED'))


if __name__ == '__main__': run()
