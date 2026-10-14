"""Existing server1 recovery facility rebound to M79; no application schedules."""
import json, os
from pathlib import Path
import subprocess, time
RECOVERY_HOME=Path.home();STATE=RECOVERY_HOME/'.local/state/prism-m79-recovery';KEY=RECOVERY_HOME/'.ssh/prism_m75_recovery'

def write(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');os.replace(temporary,path)

def rpc(method):
    p=subprocess.run(['ssh','-i',str(KEY),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=accept-new','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-p','2223','root@127.0.0.1'],input=json.dumps(dict(method=method))+'\n',capture_output=True,text=True,timeout=45)
    if p.returncode:raise RuntimeError('M79 endpoint unavailable/blocked: '+p.stdout[-500:])
    return json.loads(p.stdout.splitlines()[-1])

def transition(previous,current,now):
    waiting=current['state'] in ('NO_OWNER','RECOVERY_BLOCKED','UNREACHABLE','COMPLETED','DEADLINE')
    since=previous.get('wait_since') or now if waiting else None
    seconds=now-since if waiting else 0
    bucket=45 if seconds>=2700 else 30 if seconds>=1800 else 0
    result=dict(current,wait_since=since,wait_seconds=seconds,idle_basis='RESEARCH_WAIT_NOT_PLATFORM_IDLE',wait_bucket=bucket,
                notification_delivery='DURABLE_EVENTS; active Sol reads and informs owner; Codex automation remains PAUSED')
    alert=previous.get('state')!=current['state'] or previous.get('wait_bucket')!=bucket or previous.get('node')!=current.get('node')
    return result,alert

def main():
    STATE.mkdir(parents=True,exist_ok=True);p=STATE/'status.json';saved=json.loads(p.read_text()) if p.exists() else {}
    binding=json.loads((STATE/'binding.json').read_text());stop=binding['absolute_stop']
    while time.time()<stop:
        try:
            current=rpc('status')
            if current['execution_sha256']!=binding['execution_sha256']:raise ValueError('remote execution drift')
            if current['state']=='NO_OWNER':rpc('ensure');current=rpc('status')
        except Exception as error:current=dict(state='UNREACHABLE',error=repr(error),observed_at=time.time())
        saved,alert=transition(saved,current,time.time());saved['watchdog_pid']=os.getpid();write(p,saved)
        if alert:
            with (STATE/'events.jsonl').open('a') as stream:stream.write(json.dumps(saved)+'\n')
        if current['state'] in ('COMPLETED','DEADLINE'):break
        time.sleep(60)
    subprocess.run(['systemctl','--user','disable','prism-m79-recovery.service'],capture_output=True)

if __name__=='__main__':main()
