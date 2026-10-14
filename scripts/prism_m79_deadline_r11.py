"""Explicit owner-approved training deadline extension; pinned science stays intact."""
import argparse
import inspect
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, lock
from scripts import prism_m79_run as run, prism_m79_resume_r7 as r7

REV = 'execution-revisions/deadline-r11'
DEADLINE_ISO = '2026-10-13T01:00:00+08:00'
from datetime import datetime
TRAIN_DEADLINE = datetime.fromisoformat(DEADLINE_ISO).timestamp()


def verify():
    revision = read(ROOT / REV / 'revision.json')
    if revision['decision'] != 'APPROVED_EXPLICIT_USER_INSTRUCTION':
        raise ValueError('explicit deadline authorization missing')
    if revision['training_deadline'] != TRAIN_DEADLINE:
        raise ValueError('authorized absolute deadline drift')
    if digest(__file__) != revision['adapter_sha256']:
        raise ValueError('deadline adapter source drift')
    if digest(ROOT / 'migration-r7/revision.json') != revision['r7_revision_sha256']:
        raise ValueError('qualified relocation revision drift')
    r7.verify_binding()
    c, _ = run.verify()
    if revision['original_budget'] != read(ROOT / 'round-budget.json'):
        raise ValueError('original overall budget changed')
    if TRAIN_DEADLINE >= revision['original_budget']['deadline']:
        raise ValueError('training cannot extend beyond original whole-round deadline')
    if c['resources']['training_cpu_seconds'] != 150000:
        raise ValueError('original training CPU ceiling changed')
    return revision


def patched_pipeline(function):
    """Compose with the existing dual-node CPU accounting in one source adapter."""
    from scripts import prism_m79_dual_dispatch as dual
    source = inspect.getsource(function)
    changes = (
        ("spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)",
         "external_eval=_external_eval_cpu(ROOT);spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)+(external_eval if category=='evaluation_development' else 0.)"),
        ("allspent=sum(r.get('cpu_seconds',0) for r in journal)",
         "allspent=sum(r.get('cpu_seconds',0) for r in journal)+external_eval"),
        ("if mode=='train':wall=min(wall,64800-(time.time()-budget['started_at']))",
         "if mode=='train':wall=min(wall," + repr(TRAIN_DEADLINE) + "-time.time())"),
    )
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError('pinned controller extension site drift')
        source = source.replace(old, new)
    namespace = dict(function.__globals__, _external_eval_cpu=dual._external_eval_cpu)
    exec(compile(source, str(Path(__file__)) + '::pipeline', 'exec'), namespace)
    return namespace[function.__name__]


def patch_admit(method):
    # Retain the original paused/failed and backwards-clock checks. This changes
    # only the admission deadline, without rewriting hashed run config/state.
    return run.adapted(method, [
        ('if elapsed < 0 or elapsed >= self.config["budget"]["max_run_seconds"]:',
         'if elapsed < 0 or time.time() >= ' + repr(TRAIN_DEADLINE) + ':')])


def pipeline():
    verify()
    from scripts import prism_m79_dual_dispatch as dual
    dual._patch_pipeline_budget = patched_pipeline
    native_start = run.ProcessTree.start

    def route(self, argv, **kwargs):
        if argv[-2:] == [str(ROOT / 'scripts/prism_m79_resume_r7.py'), 'worker']:
            argv = [*argv[:-2], str(Path(__file__).resolve()), 'worker']
        return native_start(self, argv, **kwargs)

    run.ProcessTree.start = route
    return r7.pipeline()


def worker():
    verify()
    from training.prism_portable.engine.ppo.coordinator import Run
    Run._admit = patch_admit(Run._admit)
    write(ROOT / REV / 'worker-deadline.json', dict(
        status='AUTHORIZED_DEADLINE_ACTIVE', pid=os.getpid(),
        adapter_sha256=digest(__file__), training_deadline=TRAIN_DEADLINE,
        training_deadline_iso=DEADLINE_ISO, original_config_unchanged=True,
        observed_at=time.time()))
    return r7.worker()


def ensure():
    verify()
    proof = read(ROOT / REV / 'handoff.json')
    if proof['status'] != 'PASS_EXACT_FULL_STATE_DEADLINE_HANDOFF':
        raise ValueError('safe exact-state deadline handoff missing')
    from scripts.prism_dsw_ppo_process import same_process
    import psutil
    with lock(ROOT / REV / 'dispatch-control'):
        for row in reversed(read(ROOT / 'pipeline/launches.json')):
            if same_process(row['pid'], row['create_time']):
                if str(Path(__file__).resolve()) not in psutil.Process(row['pid']).cmdline():
                    raise ValueError('another live controller owner')
                return dict(row, action='LIVE_R9_OWNER_KEEP')
        native = run.subprocess.Popen

        def launch(argv, **kwargs):
            if argv[-2:] == [str(ROOT / 'scripts/prism_m79_run.py'), 'pipeline']:
                argv = [*argv[:-2], str(Path(__file__).resolve()), 'pipeline']
            return native(argv, **kwargs)

        run.subprocess.Popen = launch
        receipt = run.ensure()
        receipt.update(training_deadline=TRAIN_DEADLINE,
                       execution_revision_sha256=digest(ROOT / REV / 'revision.json'))
        write(ROOT / REV / 'launch.json', receipt)
        return receipt


def handoff():
    revision = verify()
    from scripts.prism_dsw_ppo_process import same_process
    from scripts.prism_m79_platform_guard import safe_training_state
    from scripts.prism_m67_storage import install
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import state_fingerprints
    import psutil
    import resource
    with lock(ROOT / REV / 'handoff-control'):
        destination = ROOT / REV / 'handoff.json'
        if destination.exists():
            return read(destination)
        saved = read(ROOT / 'pipeline/status.json')
        if saved['phase'] != 'TRAIN' or not same_process(saved['pid'], saved['create_time']):
            raise ValueError('expected live TRAIN owner missing')
        if saved['pid'] != revision['previous_owner']['pid'] or saved['create_time'] != revision['previous_owner']['create_time']:
            raise ValueError('controller identity changed before handoff')
        owner = psutil.Process(saved['pid'])
        expected = str(ROOT / 'scripts/prism_m79_resume_r7.py')
        if expected not in owner.cmdline():
            raise ValueError('old controller source identity mismatch')
        workers = [p for p in owner.children(recursive=True)
                   if '--relay' not in p.cmdline() and expected in p.cmdline() and p.cmdline()[-1] == 'worker']
        if len(workers) != 1:
            raise ValueError('expected exactly one training writer')
        worker = workers[0]
        install()
        r7.install_platform_compatibility()
        camp = ROOT / 'campaigns/a'
        state = Run(camp / 'run', read(camp / 'run/config.json'))
        ledger = CommitStore(camp / 'launch-ledger', read(camp / 'contract.json')['run']['arena_contract_sha256'])
        limit = min(time.time() + 300, revision['old_training_deadline'] - 60)
        while time.time() < limit:
            worker.send_signal(signal.SIGSTOP)
            killed = False
            try:
                with state._transaction():
                    with ledger.lock():
                        ledger_head, rows = ledger.load()
                        safe_training_state(state.state, rows)
                        proof = dict(run_commit=state.parent,
                            state_fingerprints=state_fingerprints(state.state),
                            launch_ledger_commit=ledger_head, phase=state.state['phase'],
                            cycle=state.state['cycle'], attempts=state.state['attempts'],
                            updates=state.state['global_step'], cursor=state.state['cursor'],
                            worker_pid=worker.pid, worker_create_time=worker.create_time(),
                            previous_owner=dict(pid=owner.pid, create_time=owner.create_time()))
                        # Durable proof BEFORE stopping; numeric commits unchanged.
                        write(ROOT / REV / 'safe-boundary.json', proof)
                        worker.kill()
                        killed = True
                break
            except (RuntimeError, ValueError) as exc:
                if 'scientific failure' in str(exc):
                    raise
            finally:
                if not killed:
                    try:
                        worker.send_signal(signal.SIGCONT)
                    except psutil.NoSuchProcess:
                        pass
            time.sleep(.15)
        else:
            raise ValueError('safe handoff boundary not found; original worker retained')
        until = time.time() + 45
        while same_process(owner.pid, saved['create_time']) and time.time() < until:
            time.sleep(.2)
        if same_process(owner.pid, saved['create_time']):
            raise ValueError('old controller did not finish real CPU accounting')
        done = ROOT / 'pipeline/train.completion.json'
        receipt = read(done)
        if receipt['status'] != 'FAIL' or receipt['resources']['returncode'] not in (-9, 247) or receipt['resources']['stop_reason'] is not None:
            raise ValueError('handoff does not match exact intentional boundary stop')
        after = Run.open(camp / 'run')
        if after.parent != proof['run_commit'] or state_fingerprints(after.state) != proof['state_fingerprints'] or ledger.load()[0] != proof['launch_ledger_commit']:
            raise ValueError('full-state or ledger changed during safe handoff')
        journal = read(ROOT / 'pipeline/resources.json')
        if any(row['state'] == 'RUNNING' for row in journal):
            raise ValueError('old real resource receipt unfinished')
        if sum(row.get('cpu_seconds', 0) for row in journal if row['category'] == 'training') >= 150000:
            raise ValueError('original training CPU budget exhausted')
        proof.update(status='PASS_EXACT_FULL_STATE_DEADLINE_HANDOFF',
            retained_completion_sha256=digest(done), retained_completion=receipt,
            original_budget=read(ROOT / 'round-budget.json'),
            training_deadline=TRAIN_DEADLINE, new_games=0, observed_at=time.time())
        done.rename(ROOT / REV / 'intentional-handoff-train.completion.json')
        usage = resource.getrusage(resource.RUSAGE_SELF)
        journal.append(dict(category='audit_transfer_control', mode='authorized_deadline_handoff',
            state='FINISHED', cpu_seconds=usage.ru_utime + usage.ru_stime,
            observed_at=time.time(), new_games=0))
        write(ROOT / 'pipeline/resources.json', journal)
        write(destination, proof)
        return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('verify', 'handoff', 'ensure', 'pipeline', 'worker'))
    args = parser.parse_args()
    print(json.dumps(globals()[args.mode]()), flush=True)
