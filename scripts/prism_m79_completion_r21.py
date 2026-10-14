"""Owner-authorized completion of M79; preserve pinned science and elapsed costs.

This independent adapter supersedes expired calendar admission only. Original
sources, checkpoint identity, shard manifests and budget evidence remain intact.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest, lock
from scripts import prism_m79_run as run, prism_m79_resume_r7 as r7

REV = ROOT / 'execution-revisions/completion-r21'
SELF = str(Path(__file__).resolve())
EXECUTION = '6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a'
# Exact durable checkpoint observed after the owner restored connectivity.
EXPECTED_HEAD = '086227e12e053922470c0a9a6a9c2a1a921be936a327bd2153980dc3ead2d70d'
EXPECTED_LEDGER = 'd4814670278ff9b2e98a6aa3d9f859e35049df785b87d49016c47a95d0f39643'


def verify():
    revision = read(REV / 'revision.json')
    if revision['adapter_sha256'] != digest(SELF) or revision['execution_sha256'] != EXECUTION:
        raise ValueError('completion adapter identity drift')
    if digest(ROOT / 'execution.json') != EXECUTION:
        raise ValueError('original execution identity drift')
    if revision['decision'] != 'AUTHORIZED_OWNER_CONTINUE_TO_COMPLETION':
        raise ValueError('owner authorization missing')
    for name, sha in revision['bindings'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('completion binding drift: ' + name)
    r7.verify_binding()
    return revision


def bounds():
    # No calendar cutoff. Each stage still has finite remaining CPU, storage,
    # RSS and a CPU-derived active-runtime watchdog; each game keeps 90 seconds.
    verify()
    return float('inf')


def patch_admit(method):
    return run.adapted(method, [
        ('if elapsed < 0 or elapsed >= self.config["budget"]["max_run_seconds"]:',
         'if elapsed < 0:')])


def patch_pipeline(function):
    from scripts import prism_m79_dual_dispatch as dual
    return run.adapted(function, [
        ("spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)",
         "external_eval=_external_eval_cpu(ROOT);spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)+(external_eval if category=='evaluation_development' else 0.)"),
        ("allspent=sum(r.get('cpu_seconds',0) for r in journal)",
         "allspent=sum(r.get('cpu_seconds',0) for r in journal)+external_eval"),
        ("wall=remaining\n                if mode=='train':wall=min(wall,64800-(time.time()-budget['started_at']))",
         "wall=max(90.,left*2)  # finite active-runtime watchdog, excludes past downtime"),
        ("deadline=budget['deadline']", "deadline=None,execution_revision='completion-r21'"),
    ], {'_external_eval_cpu': dual._external_eval_cpu})


def install():
    verify()
    run.bounds = bounds
    native_verify = run.verify

    def local_verify():
        c, p = native_verify()
        p = copy.deepcopy(p)
        p['binding']['evaluation_affinity'] = [0, 1, 2, 3]
        return c, p

    run.verify = local_verify
    from scripts import prism_m79_evaluate as e, prism_bounded_eval as b
    e.bounds = bounds
    e.verify = local_verify
    # Keep original policies/manifests byte-identical. The revision authorizes
    # removal of expired admission; original per-game timeouts remain effective.
    b.prepare = run.adapted(b.prepare, [
        ('require(policy["deadline_unix"] > time.time(), "deadline exhausted")',
         'completion_authorization()')], {'completion_authorization': verify})
    b.launch = run.adapted(b.launch, [
        ('wall = min(validated["config"]["timeouts"]["game_wall_seconds"],\n               policy["deadline_unix"] - time.time())',
         'wall = validated["config"]["timeouts"]["game_wall_seconds"]'),
        ('remaining_wall = min(wall, max(0., policy["deadline_unix"] - time.time()))',
         'remaining_wall = max(0., wall - (time.monotonic() - admitted_at))'),
        ('require(wall > 0 and remaining_cpu > 0, "resource budget exhausted")',
         'require(wall > 0 and remaining_cpu > 0, "resource budget exhausted"); admitted_at = time.monotonic()')])
    # Child shards enter this same revision; changing only the parent is unsafe.
    e.dispatch = run.adapted(e.dispatch, [
        ("str(Path(__file__).resolve()),'grid'", "completion_entry,'grid'")],
        {'completion_entry': SELF})
    return e


def no_writer():
    import psutil
    conflicts = []
    ancestors = {p.pid for p in psutil.Process().parents()}
    for p in psutil.process_iter(['pid', 'cmdline', 'status']):
        try:
            argv = p.info['cmdline'] or []
            if p.pid == os.getpid() or p.pid in ancestors or p.info['status'] == psutil.STATUS_ZOMBIE:
                continue
            if any(str(ROOT) in a for a in argv) and not any(a.endswith('/probe.py') for a in argv):
                conflicts.append(dict(pid=p.pid, argv=argv))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if conflicts:
        raise ValueError('existing execution process; reconcile identity first: ' + repr(conflicts))


def reconcile():
    verify(); run.verify()
    with lock(REV / 'reconcile-control'):
        if (REV / 'reconciliation.json').exists():
            return read(REV / 'reconciliation.json')
        no_writer()
        r7.install_platform_compatibility()
        from training.prism_portable.engine.ppo.coordinator import Run
        from training.prism_portable.engine.ppo.store import CommitStore
        from training.prism_portable.protocol import state_fingerprints
        from scripts.prism_m79_platform_guard import safe_training_state
        from scripts import prism_m79_dual_dispatch as dual
        state = Run.open(ROOT / 'campaigns/a/run')
        spec = read(ROOT / 'campaigns/a/contract.json')
        ledger_head, ledger = CommitStore(ROOT / 'campaigns/a/launch-ledger', spec['run']['arena_contract_sha256']).load()
        if state.parent != EXPECTED_HEAD or ledger_head != EXPECTED_LEDGER:
            raise ValueError('observed durable state changed before recovery')
        safe_training_state(state.state, ledger)
        if (state.state['attempts'], state.state['global_step'], len(ledger['attempts'])) != (4124, 886, 4124):
            raise ValueError('observed counts changed')
        journal = read(ROOT / 'pipeline/resources.json')
        if any(r['state'] == 'RUNNING' for r in journal):
            raise ValueError('unreconciled previous CPU accounting')
        spent = {c: sum(r.get('cpu_seconds', 0) for r in journal if r['category'] == c)
                 for c in ('training', 'evaluation_development', 'audit_transfer_control')}
        spent['evaluation_development'] += dual._external_eval_cpu(ROOT)
        if any(spent[k] >= v for k, v in [('training',150000),('evaluation_development',120000),('audit_transfer_control',30000)]) or sum(spent.values()) >= 300000:
            raise ValueError('remaining original CPU capacity exhausted')
        stop_path = ROOT / 'pipeline/train.completion.json'
        stop = read(stop_path)
        if stop['status'] != 'FAIL' or stop['resources']['stop_reason'] != 'wall_deadline':
            raise ValueError('only the verified calendar stop is reconciled')
        from training.prism_portable.processes import directory_bytes
        import shutil
        occupied = directory_bytes(ROOT)
        free = shutil.disk_usage(ROOT).free
        if free < max(0, 40802189312 - occupied) + 8589934592:
            raise ValueError('remaining storage reservation unavailable')
        write(REV / 'previous-status.json', read(ROOT / 'pipeline/status.json'))
        write(REV / 'previous-resources.json', journal)
        write(REV / 'previous-train.completion.json', stop)
        proof = dict(status='PASS_EXACT_FULL_STATE_COMPLETION_RECONCILIATION',
                     run_commit=state.parent, ledger_commit=ledger_head,
                     fingerprints=state_fingerprints(state.state), attempts=4124, updates=886,
                     original_stop_sha256=digest(stop_path), cpu_spent=spent,
                     disk_free=free, root_bytes=occupied, node=platform.node(),
                     original_budget=read(ROOT / 'round-budget.json'),
                     new_games=0, observed_at=time.time())
        write(REV / 'reconciliation.json', proof)
        # Archive only this known operational stop; keep resource charges intact.
        stop_path.rename(REV / 'retained-train.completion.json')
        return proof


def ensure():
    verify(); run.verify()
    import psutil
    from scripts.prism_dsw_ppo_process import same_process
    with lock(ROOT / 'launch-control'):
        launch_path = REV / 'launch.json'
        if launch_path.exists():
            old = read(launch_path)
            if old['node'] == platform.node() and same_process(old['pid'], old['create_time']):
                if SELF not in psutil.Process(old['pid']).cmdline():
                    raise ValueError('live owner command differs')
                return dict(old, action='LIVE_OWNER_KEEP')
            raise ValueError('r21 launch already used; inspect retained failure before retry')
        reconcile()
        no_writer()
        # One newly authorized launch; old launch history and failures retained.
        launches = read(ROOT / 'pipeline/launches.json')
        with (REV / 'supervisor.log').open('xb') as log:
            p = subprocess.Popen([sys.executable, '-B', SELF, 'pipeline'], cwd=ROOT,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        receipt = dict(status='STARTED_COMPLETION_R21', node=platform.node(), pid=p.pid,
                       create_time=psutil.Process(p.pid).create_time(), observed_at=time.time(),
                       execution_sha256=EXECUTION, adapter_sha256=digest(SELF),
                       calendar_deadline=None, authorized_additional_launches=1)
        launches.append(receipt); write(ROOT / 'pipeline/launches.json', launches)
        write(launch_path, receipt)
        return receipt


def pipeline():
    install()
    native_start = run.ProcessTree.start

    def route(self, argv, **kwargs):
        modules = {'prism_m79_run.py':'worker', 'prism_m79_audit.py':'audit',
                   'prism_m79_report.py':'report', 'prism_m79_evaluate.py':None}
        for i, arg in enumerate(argv):
            if arg.startswith(str(ROOT / 'scripts')) and Path(arg).name in modules:
                mode = modules[Path(arg).name]
                argv = [*argv[:i], SELF, *(argv[i+1:] if mode is None else [mode])]
                break
        return native_start(self, argv, **kwargs)

    run.ProcessTree.start = route
    return patch_pipeline(run.pipeline)()


def execute(mode, output=None):
    e = install()
    if mode == 'worker':
        from training.prism_portable.engine.ppo.coordinator import Run
        Run._admit = patch_admit(Run._admit)
        write(REV / 'worker-admission.json', dict(calendar_deadline=None,
              cpu_budget=150000, target_cycle=20, pid=os.getpid(), observed_at=time.time()))
        return r7.worker()
    if mode == 'audit':
        return r7.audit()
    if mode == 'report':
        from scripts.prism_m79_report import build
        return build(ROOT)
    if mode == 'grid':
        return e.grid(output)
    if mode == 'evaluate':
        from scripts import prism_m79_dual_dispatch as dual
        checked = run.adapted(dual.control_evaluate, [
            ('if time.time() >= state["deadline"]:\n        raise ValueError("original M79 deadline reached")',
             'completion_authorization()')], {'completion_authorization': verify})
        return checked(ROOT)
    return getattr(e, mode)()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('reconcile','ensure','pipeline','worker','audit','report','candidates','curve','evaluate','grid'))
    parser.add_argument('--output')
    args = parser.parse_args()
    result = globals()[args.mode]() if args.mode in ('reconcile','ensure','pipeline') else execute(args.mode,args.output)
    print(json.dumps(result, ensure_ascii=False), flush=True)
