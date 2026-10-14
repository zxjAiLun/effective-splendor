"""One-shot platform stop guard; no recurring observation or numeric hot patch.

The current worker remains r6. This separately hashed operational adapter can
stop it only while its committed store is locked and no game is unresolved.
Only the exact resulting infrastructure stop may be reconciled on startup.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, lock


def verify_binding():
    binding = read(ROOT / 'platform-stop/binding.json')
    if digest(__file__) != binding['adapter_sha256']:
        raise ValueError('platform guard source drift')
    if digest(ROOT / 'execution.json') != binding['execution_sha256']:
        raise ValueError('platform guard execution drift')
    if digest(ROOT / 'execution-revisions/r6.json') != binding['execution_revision_sha256']:
        raise ValueError('platform guard r6 drift')
    if read(ROOT / 'round-budget.json') != binding['original_budget']:
        raise ValueError('original scientific budget changed')
    return binding


def safe_training_state(state, ledger):
    if state['phase'] not in ('READY', 'COLLECTING', 'UPDATING', 'COMMITTED') or ledger['failed']:
        raise ValueError('scientific failure cannot be platform-paused')
    if any(j['status'] not in ('COMPLETE', 'TRUNCATED') for j in state['jobs'].values()):
        raise ValueError('wait for current game publication and ingestion')
    if any(j['status'] not in ('COMPLETE', 'TRUNCATED', 'INFRA_ABORT') for j in ledger['attempts'].values()):
        raise ValueError('wait for physical ledger commit')


def verify_pause(pause, current_commit, current_fingerprints, completion_sha):
    if pause['status'] != 'PAUSED_SAFE_FULL_STATE' or pause['stage'] != 'train':
        raise ValueError('stop requires explicit reconciliation')
    if pause['run_commit'] != current_commit or pause['state_fingerprints'] != current_fingerprints:
        raise ValueError('paused full state changed')
    if pause['stage_completion_sha256'] != completion_sha:
        raise ValueError('not the retained platform interruption')


def stop_training(binding, owner, worker):
    import psutil
    from scripts.prism_m67_storage import install
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import state_fingerprints
    install()
    camp = ROOT / 'campaigns/a'
    spec = read(camp / 'contract.json')
    # Load once; the transaction reloads the current head after acquiring its lock.
    run = Run.open(camp / 'run')
    ledger_store = CommitStore(camp / 'launch-ledger', spec['run']['arena_contract_sha256'])
    limit = min(binding['stop_at'] + 600, binding['estimated_platform_stop'] - 600)
    while time.time() < limit:
        if not worker.is_running() or worker.status() == psutil.STATUS_ZOMBIE:
            return None
        worker.send_signal(signal.SIGSTOP)
        killed = False
        try:
            with run._transaction():
                with ledger_store.lock():
                    head, ledger = ledger_store.load()
                    safe_training_state(run.state, ledger)
                    proof = dict(run_commit=run.parent, state_fingerprints=state_fingerprints(run.state),
                                 launch_ledger_commit=head, phase=run.state['phase'], cycle=run.state['cycle'],
                                 attempts=run.state['attempts'], global_step=run.state['global_step'],
                                 cursor=run.state['cursor'], worker_pid=worker.pid,
                                 worker_create_time=worker.create_time())
                    worker.kill()
                    killed = True
            return proof
        except (RuntimeError, ValueError) as exc:
            # A busy commit or in-flight game is allowed to finish; no pause flag
            # is injected into Campaign.work, which would mark a fatal failure.
            if 'scientific failure' in str(exc):
                raise
        finally:
            if not killed:
                try:
                    worker.send_signal(signal.SIGCONT)
                except psutil.NoSuchProcess:
                    pass
        time.sleep(.25)
    raise ValueError('no safe training boundary before reserved platform stop window')


def guard():
    import psutil
    from scripts.prism_dsw_ppo_process import same_process
    binding = verify_binding()
    directory = ROOT / 'platform-stop'
    write(directory / 'armed.json', dict(status='ARMED_ONE_SHOT', pid=os.getpid(),
          create_time=psutil.Process().create_time(), stop_at=binding['stop_at'],
          adapter_sha256=digest(__file__), observed_at=time.time()))
    # This is one deadline wait, not an SSH poller or ongoing research monitor.
    time.sleep(max(0, binding['stop_at'] - time.time()))
    verify_binding()
    saved = read(ROOT / 'pipeline/status.json')
    if (ROOT / 'pipeline/completion.json').exists() or not same_process(saved['pid'], saved['create_time']):
        write(directory / 'pause.json', dict(status='NO_LIVE_OWNER_AT_PLATFORM_STOP', observed_at=time.time()))
        return
    owner = psutil.Process(saved['pid'])
    expected = str(ROOT / 'scripts/prism_m79_revision_r6.py')
    if expected not in owner.cmdline():
        raise ValueError('platform stop owner identity mismatch')
    children = owner.children(recursive=True)
    workers = [p for p in children if expected in p.cmdline() and p.cmdline()[-1] == 'worker']
    if saved['phase'] != 'TRAIN' or len(workers) != 1:
        # Preserve the existing owned relay and stage result; later inspection
        # must distinguish interrupted audit/report from a scientific failure.
        owner.terminate()
        pause = dict(status='PLATFORM_INTERRUPTION_REQUIRES_RECONCILIATION', stage=saved['phase'].lower())
    else:
        proof = stop_training(binding, owner, workers[0])
        if proof is None:
            write(directory / 'pause.json', dict(status='WORKER_FINISHED_BEFORE_SAFE_STOP', observed_at=time.time()))
            return
        # The existing relay publishes real CPU usage; coordinator retains FAIL.
        until = time.time() + 45
        while same_process(saved['pid'], saved['create_time']) and time.time() < until:
            time.sleep(.2)
        if same_process(saved['pid'], saved['create_time']):
            raise ValueError('coordinator did not retain platform interruption receipt')
        done = ROOT / 'pipeline/train.completion.json'
        completion = read(done)
        # The worker is killed at its committed boundary. Its relay's Python
        # SystemExit(-9) becomes 247 at the outer POSIX process boundary.
        if completion['status'] != 'FAIL' or completion['resources']['returncode'] not in (-9, 247):
            raise ValueError('unexpected training stop evidence')
        pause = dict(proof, status='PAUSED_SAFE_FULL_STATE', stage='train',
                     stage_completion_sha256=digest(done), retained_stage_completion=completion)
    pause.update(owner_pid=saved['pid'], owner_create_time=saved['create_time'],
                 execution_sha256=binding['execution_sha256'], original_budget=binding['original_budget'],
                 observed_at=time.time(), reason='user reported instance auto shutdown in about 6.5 hours')
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    pause['guard_cpu_seconds'] = usage.ru_utime + usage.ru_stime
    os.sync()
    write(directory / 'pause.json', pause)


def ensure():
    verify_binding()
    from scripts.prism_m79_revision_r6 import ensure as start
    path = ROOT / 'platform-stop/pause.json'
    if not path.exists():
        return start()
    pause = read(path)
    if pause['status'] == 'NO_LIVE_OWNER_AT_PLATFORM_STOP':
        return start()
    if time.time() >= pause['original_budget']['deadline']:
        raise ValueError('original scientific deadline exhausted; platform pause does not extend it')
    with lock(ROOT / 'platform-resume-control'):
        receipt = ROOT / 'platform-stop/resume.json'
        if receipt.exists():
            return start()
        from scripts.prism_m67_storage import install
        from training.prism_portable.engine.ppo.coordinator import Run
        from training.prism_portable.engine.ppo.store import CommitStore
        from training.prism_portable.protocol import state_fingerprints
        from scripts.prism_dsw_ppo_process import same_process
        install()
        if same_process(pause['owner_pid'], pause['owner_create_time']):
            raise ValueError('platform pause owner still live')
        run = Run.open(ROOT / 'campaigns/a/run')
        spec = read(ROOT / 'campaigns/a/contract.json')
        head, ledger = CommitStore(ROOT / 'campaigns/a/launch-ledger', spec['run']['arena_contract_sha256']).load()
        safe_training_state(run.state, ledger)
        if head != pause['launch_ledger_commit']:
            raise ValueError('paused physical ledger drift')
        done = ROOT / 'pipeline/train.completion.json'
        verify_pause(pause, run.parent, state_fingerprints(run.state), digest(done))
        # Preserve the exact failure and costs; only this named platform stop is
        # reconciled. Original source, seeds, all commits and budget stay intact.
        done.rename(ROOT / 'platform-stop/train-interruption.completion.json')
        journal = read(ROOT / 'pipeline/resources.json')
        journal.append(dict(category='audit_transfer_control', mode='platform_stop_guard', state='FINISHED',
                            cpu_seconds=pause['guard_cpu_seconds'], accounting_scope='one-shot guard self CPU'))
        write(ROOT / 'pipeline/resources.json', journal)
        write(receipt, dict(status='PASS_EXACT_PLATFORM_FULL_STATE_RESUME', pause_sha256=digest(path),
                           state_fingerprints=state_fingerprints(run.state), run_commit=run.parent,
                           observed_at=time.time(), original_budget=pause['original_budget'], new_games=0))
    return start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['guard', 'ensure', 'endpoint'])
    args = parser.parse_args()
    if args.mode == 'endpoint':
        method = json.loads(sys.stdin.readline())['method']
        if method == 'status':
            from scripts.prism_m79_revision_r6 import status
            print(json.dumps(status()))
        elif method == 'ensure':
            print(json.dumps(ensure()))
        else:
            raise ValueError('restricted platform recovery method')
    elif args.mode == 'guard':
        guard()
    else:
        print(json.dumps(ensure()))
