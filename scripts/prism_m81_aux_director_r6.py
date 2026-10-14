"""Finite server1 delivery chain; no research dispatch and no user notifications."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
REMOTE = '/mnt/workspace/splendor-m81-delivery-r6'
PY = '/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
SCRIPT = REMOTE + '/prism_m81_aux_delivery_r6.py'
START = (json.loads((HERE/'launch.json').read_text())['started_at']
         if (HERE/'launch.json').exists() else time.time())
DEADLINE = START + 7*3600


def save(**value):
    value.update(observed_at=time.time(), started_at=START, deadline=DEADLINE)
    path = HERE/'status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def ssh(port, args, timeout=120, **kwargs):
    return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',
                           '-p',str(port),'root@127.0.0.1',*args],
                          timeout=min(timeout, max(1, DEADLINE-time.time())), check=True, **kwargs)


def query(port, code):
    p = ssh(port, [PY, '-B', '-'], input=code, text=True, capture_output=True)
    return json.loads(p.stdout.splitlines()[-1])


def transfer_to(port, source, target):
    subprocess.run(['scp','-q','-o','BatchMode=yes','-P',str(port),str(source),
                    'root@127.0.0.1:'+target],check=True,timeout=900)


def deliver():
    code = '''from pathlib import Path
import zipfile,json,hashlib
r=Path(REMOTE)
names=['supplement.md','supplement.json','profile-completion.json','profile-status.json',
       'baseline-profile-completion.json','import.json','launch.json','failure.json',
       'archive-receipt.json','archive-members.jsonl','archive-exit.json']
p=r/'delivery.zip'
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
 for n in names:
  if (r/n).exists():z.write(r/n,n)
 for f in (r/'profiles').glob('*.json'):z.write(f,'profiles/'+f.name)
print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}))
'''.replace('REMOTE', repr(REMOTE))
    identity = query(2223, code)
    target = HERE/'delivery.zip'
    with target.open('wb') as stream:
        ssh(2223, ['cat', REMOTE+'/delivery.zip'], timeout=900, stdout=stream)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == identity['sha256']
    transfer_to(2222, target, REMOTE+'/delivery.zip')
    got = query(2222, 'import hashlib,json\nfrom pathlib import Path\np=Path('+repr(REMOTE+'/delivery.zip')+')\nprint(json.dumps({"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}))')
    assert got['sha256'] == identity['sha256']
    (HERE/'delivery-receipt.json').write_text(json.dumps(identity))
    return identity


def main():
    save(state='WAITING_FINAL_EVALUATION_SNAPSHOT', dsw2='baseline profiles already running')
    while time.time()-START < 2*3600:
        result = ssh(2222, [PY, '-B', SCRIPT, 'snapshot'], timeout=900, capture_output=True, text=True)
        receipt = json.loads(result.stdout.splitlines()[-1])
        if receipt['status'] == 'PASS':
            break
        time.sleep(30)
    else:
        raise TimeoutError('final evaluation not available within auxiliary transfer allowance')
    save(state='TRANSFERRING_FINISHED_EVALUATION', snapshot=receipt)
    bundle = HERE/'snapshot.zip'
    if not bundle.exists() or hashlib.sha256(bundle.read_bytes()).hexdigest() != receipt['sha256']:
        with bundle.open('wb') as stream:
            ssh(2222, ['cat', REMOTE+'/snapshot.zip'], timeout=900, stdout=stream)
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == receipt['sha256']
    transfer_to(2223, bundle, REMOTE+'/snapshot.zip')
    ssh(2223, [PY, '-B', SCRIPT, 'import', receipt['sha256']], timeout=900)
    while True:
        status = query(2223, 'from pathlib import Path\nimport json\nr=Path('+repr(REMOTE)+')\np=r/"baseline-profile-completion.json"\nf=r/"failure.json"\nprint(json.dumps(json.loads(p.read_text()) if p.exists() else {"status":"FAIL" if f.exists() else "RUNNING"}))')
        if status['status'] == 'PASS':
            break
        if status['status'] == 'FAIL':
            raise RuntimeError('baseline supplemental profile failed')
        if time.time()-START > 3*3600:
            raise TimeoutError('baseline profile completion unavailable')
        time.sleep(15)
    save(state='PROFILING_FULL_EVALUATION', snapshot=receipt)
    ssh(2223, [PY, '-B', SCRIPT, 'complete'], timeout=7200)
    identity = deliver()
    save(state='PROFILE_DELIVERED_ARCHIVING', delivery=identity)
    # Private immutable evaluation snapshot only. No deletion requested.
    archive = ['python3', REMOTE+'/prism_remote_history_archive.py',
               '--source', REMOTE+'/data', '--prefix', 'splendor/m81/evaluation-delivery-r6-'+receipt['sha256'][:16],
               '--manifest-out', REMOTE+'/archive-receipt.json',
               '--members-out', REMOTE+'/archive-members.jsonl',
               '--deadline-seconds', '10800', '--cpu-seconds', '18000']
    try:
        with (HERE/'archive.log').open('wb') as log:
            ssh(2223, archive, timeout=10900, stdout=log, stderr=subprocess.STDOUT)
        archive_state = 'PASS'
    except (subprocess.SubprocessError, OSError) as exc:
        archive_state = 'FAILED_RETAINED_LOCAL_SOURCE'
        save(state=archive_state, error=type(exc).__name__, profile_delivery=identity)
    query(2223, 'import json\nfrom pathlib import Path\np=Path('+repr(REMOTE+'/archive-exit.json')+')\np.write_text('+repr(json.dumps({'status':archive_state}))+')\nprint("{}")')
    identity = deliver()
    save(state='COMPLETED' if archive_state == 'PASS' else archive_state, delivery=identity,
         archive=archive_state, new_games=0)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        save(state='FAILED_RETAINED_EVIDENCE', error=repr(error))
        raise
