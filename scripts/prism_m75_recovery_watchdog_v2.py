"""Stable server1 watchdog for the finite M75 recovery contract. No stored tokens."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

DEADLINE = 1791744630.7118258
STATE = Path.home() / '.local/state/prism-m75-recovery'
KEY = Path.home() / '.ssh/prism_m75_recovery'
TOKEN = None  # Stable broker memory; survives DSW instance replacements, never written.


def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    os.replace(temp, path)


def rpc(node, request):
    port = {'dsw': 2222, 'dsw2': 2223}[node]
    p = subprocess.run(['ssh', '-i', str(KEY), '-o', 'IdentitiesOnly=yes',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                        '-o', 'StrictHostKeyChecking=accept-new',
                        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                        '-p', str(port), 'root@127.0.0.1'],
                       input=json.dumps(request)+'\n', capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise RuntimeError('endpoint unavailable or blocked')
    result = json.loads(p.stdout.splitlines()[-1])
    if result.get('state') == 'RECOVERY_BLOCKED':
        raise RuntimeError('recovery blocked: '+result.get('error_type', 'unknown'))
    return result


def idle_bucket(seconds):
    return 45 if seconds >= 2700 else 30 if seconds >= 1800 else 0


def transition(previous, current, now):
    """Return durable alert state; logical wait is distinct from platform idle."""
    state = current['state']
    prior_state = previous.get('state')
    idle = state in ('IDLE_WAIT', 'NO_OWNER', 'COMPLETED', 'RECOVERY_BLOCKED')
    since = previous.get('idle_since', now) if idle and prior_state in ('IDLE_WAIT','NO_OWNER','COMPLETED','RECOVERY_BLOCKED') else now
    result = dict(current, idle_since=since if idle else None,
                  idle_basis='RESEARCH_WAIT_NOT_PLATFORM_COUNTER',
                  idle_seconds=max(0., now-since) if idle else 0.)
    bucket = idle_bucket(result['idle_seconds']) if idle else None
    old_bucket = previous.get('idle_bucket')
    result['idle_bucket'] = bucket
    changed_node = previous.get('node') != current.get('node') and previous.get('node') is not None
    alert = state != prior_state or changed_node or (idle and bucket != old_bucket)
    return result, alert


def cycle(saved):
    global TOKEN
    try:TOKEN=rpc('dsw', {'method':'credential'})['token']
    except Exception:pass
    now=time.time();nodes={};events=[]
    for node in ('dsw', 'dsw2'):
        try:
            current=rpc(node, {'method':'status'})
            if current['state']=='NO_OWNER' and now<DEADLINE:
                request={'method':'ensure'}
                if TOKEN:request['token']=TOKEN
                elif node=='dsw2':raise RuntimeError('credential cache unavailable')
                rpc(node, request)
                current=rpc(node, {'method':'status'})
        except Exception as error:
            current=dict(state='UNREACHABLE_OR_RECOVERY_BLOCKED', observed_at=time.time(),
                         error_type=type(error).__name__)
        current['role']=node
        entry, changed=transition(saved.get('nodes',{}).get(node,{}), current, now)
        nodes[node]=entry
        if changed:
            event=dict(role=node, state=entry['state'], idle_seconds=entry['idle_seconds'],
                       idle_bucket=entry['idle_bucket'], observed_at=now,
                       node=entry.get('node'), phase=entry.get('phase'),
                       attention=entry['state'] not in ('RUNNING',))
            events.append(event)
            with (STATE/'events.jsonl').open('a') as stream:
                stream.write(json.dumps(event)+'\n')
    result=dict(observed_at=now, deadline=DEADLINE, nodes=nodes,
                watchdog_pid=os.getpid(), execution_state='ACTIVE' if now<DEADLINE else 'DEADLINE',
                notification_delivery='CODEX_THREAD_HEARTBEAT', credential_cache='AVAILABLE_MEMORY_ONLY' if TOKEN else 'UNAVAILABLE', new_events=events)
    write(STATE/'status.json', result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--once', action='store_true');args=parser.parse_args()
    STATE.mkdir(parents=True,exist_ok=True)
    saved=json.loads((STATE/'status.json').read_text()) if (STATE/'status.json').exists() else {}
    while True:
        saved=cycle(saved)
        if args.once or time.time()>=DEADLINE:break
        time.sleep(60)
