"""M75 r6: restart recovery, preserving pinned r4 code and completed games.

Deploy as ROOT/reboot-resume-r7/recovery.py. The SSH endpoint accepts JSON only.
Credentials travel through stdin/process memory; none enter receipts or argv.
"""
import argparse
try:
    import fcntl
except ImportError:  # Pure admission helpers are also tested on Windows.
    fcntl = None
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REV = ROOT / 'reboot-resume-r7'
from training.prism_portable.common import read, write, digest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract():
    p = read(REV / 'policy.json')
    if digest(__file__) != p['adapter_sha256']:
        raise ValueError('r6 source drift')
    if digest(ROOT / 'eval-handoff-r4/policy.json') != p['r4_policy_sha256']:
        raise ValueError('r4 policy drift')
    if time.time() >= p['deadline']:
        raise ValueError('finite M75 deadline exhausted')
    return p


def live(record):
    try:
        process = psutil.Process(record['pid'])
        argv = process.cmdline()
        # Historical coordinators were forked from python stdin launchers;
        # their argv is python '-', so bind the recorded policy as well.
        source_bound = record.get('policy_sha256') in {
            digest(path) for path in (ROOT/'eval-handoff-r4/policy.json',
                                      ROOT/'wait-resume-r5/policy.json', REV/'policy.json')
            if path.exists()}
        argv_bound = any(str(ROOT) in arg for arg in argv) or (source_bound and len(argv)>=2 and argv[-1]=='-' and 'python' in Path(argv[0]).name)
        return (abs(process.create_time() - record['create_time']) < .01
                and process.status() != psutil.STATUS_ZOMBIE and argv_bound)
    except (psutil.NoSuchProcess, KeyError):
        return False


def status():
    p = read(REV / 'policy.json')
    result = dict(node=os.uname().nodename, observed_at=time.time(), deadline=p['deadline'],
                  role=p['role'], state='NO_OWNER', owners=[], free_bytes=psutil.disk_usage(ROOT).free)
    completion = ROOT / 'eval-handoff-r4/completion.json'
    if completion.exists():
        done = read(completion)
        if done.get('state') in ('COMPLETED', 'PASS_EVALUATION_DELIVERED'):
            result.update(state='COMPLETED', completion=done)
            return result
    for relative in ('reboot-resume-r7/launch.json', 'eval-handoff-r4/status.json',
                     'eval-handoff-r4/launch.json', 'wait-resume-r5/launch.json'):
        path = ROOT / relative
        if path.exists():
            record = read(path)
            if live(record):
                result['owners'].append(record)
    current = ROOT / 'eval-handoff-r4/status.json'
    if current.exists():
        result['phase'] = read(current).get('phase')
    if result['owners']:
        result['state'] = 'RUNNING'
        if str(result.get('phase', '')).startswith('WAIT_'):
            result['state'] = 'IDLE_WAIT'
    if time.time() >= p['deadline']:
        result['state'] = 'DEADLINE'
    failure = REV / 'failure.json'
    if failure.exists():
        result['last_recovery_failure'] = read(failure)
    return result


def archive_path(path, reason):
    """Move only this execution's unfinished output, retaining every old byte."""
    path = Path(path)
    target = ROOT / 'development/recovery-r7' / (reason + '-' + str(time.time_ns()))
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    return target


def pending_jobs(jobs, entries, key):
    return [job for job in jobs if entries.get(key(job), {}).get('state') == 'DISPATCHED'
            or key(job) not in entries]


def training_interval(native, rows, pure=False):
    seats = {}
    for row in rows:
        group = seats.setdefault(row['seed'], set())
        if row['candidate_seat'] in group:
            raise ValueError('duplicate training seat')
        group.add(row['candidate_seat'])
    if not seats or any(group != {0,1} for group in seats.values()):
        return dict(ci95=[None, None], seed_blocks=None, status='NOT_MEASURED_UNPAIRED',
                    scope='retained training cap; no imputation or extra games')
    return native(rows, pure)


def resume_grid(output):
    """Validate completed rows; replay only an interrupted, uncommitted attempt."""
    from scripts import prism_bounded_eval as b
    output = Path(output).resolve()
    with (output / 'r6-owner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validated, policy = b.load_bound(output)
        if not (output / 'ledger.json').exists():
            return b.run(output)
        b.inspect(output)  # includes evidence hashes and all committed rows
        ledger = b.read(output / 'ledger.json')
        if ledger['execution_state'] == 'FINISHED':
            return b.inspect(output)
        if any(e.get('kind') == 'UNKNOWN_OR_RESOURCE_FAILURE' for e in ledger['entries'].values()):
            raise ValueError('scientific/resource failure requires review, not reboot retry')
        jobs = b.legacy.jobs(validated['config'])
        pending = pending_jobs(jobs, ledger['entries'], lambda job: b.fixed._game_key(*job))
        ledger['execution_state'] = 'RUNNING'
        b.write(output / 'ledger.json', ledger)
        try:
            for job in pending:
                contract(); b.load_bound(output); b.fixed.check_assets(validated)
                key = b.fixed._game_key(*job)
                directory = b.legacy.game_directory(output, job)
                if directory.exists():
                    # Recover a finished game whose ledger write was interrupted.
                    try:
                        resources = b.read(directory / 'process-result.json')
                        cpu = b.validate_resources(resources, b.rollout_command(validated, policy, directory))
                        if b.read(directory / 'match-config.json') != b.match_config(validated, job):
                            raise ValueError('interrupted match identity drift')
                        entry = b.validate_artifacts(directory, validated['config'], job, policy['ply_cap'])
                    except (FileNotFoundError, ValueError, KeyError):
                        # A terminal game with inconsistent identity is never replayed.
                        if (directory / 'game.json').exists():
                            raise ValueError('saved game is invalid; refusing replay')
                        attempts = output / 'recovery-attempts'
                        attempts.mkdir(exist_ok=True)
                        history = attempts / hashlib.sha256(key.encode()).hexdigest()
                        if history.exists():
                            raise ValueError('one infrastructure retry per fixed game exhausted')
                        directory.rename(history)
                        b.write(history / 'r6-interruption.json', dict(kind='INFRASTRUCTURE_ABORT',
                                outcome='UNKNOWN', fixed_game_key=key, retry=1, observed_at=time.time(),
                                original_manifest_sha256=digest(output / 'manifest.json')))
                    else:
                        b.write(directory / 'game.json', entry)
                        ledger['entries'][key] = dict(entry, evidence_sha256=b.evidence(directory))
                        # Reproduce dispatch-order arithmetic below, including recovered rows.
                        total = 0.
                        for prior in jobs:
                            prior_key = b.fixed._game_key(*prior)
                            if ledger['entries'].get(prior_key, {}).get('state') != 'DISPATCHED' and prior_key in ledger['entries']:
                                total += b.read(b.legacy.game_directory(output, prior) / 'process-result.json')['cpu_seconds']
                        ledger['consumed_cpu_seconds'] = total
                        b.write(output / 'ledger.json', ledger)
                        continue
                remaining = policy['cpu_seconds'] - ledger['consumed_cpu_seconds']
                b.require(remaining > 0, 'shard CPU budget exhausted')
                b.require(time.time() + validated['config']['timeouts']['game_wall_seconds'] <= policy['deadline_unix'], 'deadline exhausted')
                b.require(b.directory_bytes(output) < policy['storage_bytes'], 'storage budget exhausted')
                ledger['entries'][key] = {'state': 'DISPATCHED'}
                b.write(output / 'ledger.json', ledger)
                entry = b.evaluate(validated, policy, output, job, remaining)
                ledger['consumed_cpu_seconds'] += entry.pop('cpu_seconds')
                ledger['entries'][key] = dict(entry, evidence_sha256=b.evidence(directory))
                b.write(output / 'ledger.json', ledger)
                b.require(sum(e.get('kind') == 'PLY_CAP_TRUNCATED' for e in ledger['entries'].values()) <= policy['max_truncated_games'], 'cap budget exhausted')
            ledger['execution_state'] = 'FINISHED'
        except BaseException:
            ledger['execution_state'] = 'STOPPED'
            raise
        finally:
            b.write(output / 'ledger.json', ledger)
            b.write(output / 'grid-status.json', b.summary(validated['config'], ledger))
        return b.inspect(output)


def install_adapters(m):
    """Patch only the new process's call graph. Pinned files stay unchanged."""
    from scripts import prism_m75_evaluate as e, prism_bounded_eval as b
    native_freeze = e.freeze_shard
    def freeze(label, cfg, cap=512):
        dest = ROOT / 'evaluation' / label
        if (dest / 'manifest.json').exists():
            validated, pol = b.load_bound(dest)
            if validated['config'] != cfg or pol['ply_cap'] != cap:
                raise ValueError('saved shard identity drift')
            return dict(label=label, output=str(dest), planned_games=len(b.legacy.jobs(cfg)), manifest_sha256=digest(dest / 'manifest.json'))
        return native_freeze(label, cfg, cap)
    e.freeze_shard = freeze
    native_dispatch = e.dispatch
    def dispatch(shards, limit=4, truncation_limit=16):
        complete, pending = [], []
        for shard in shards:
            dest = Path(shard['output'])
            if (dest / 'ledger.json').exists() and read(dest / 'ledger.json')['execution_state'] == 'FINISHED':
                complete.append(dict(shard, grid=b.inspect(dest)))
            else:
                pending.append(shard)
        caps = sum(s['grid']['truncated_games'] for s in complete)
        if caps > truncation_limit:
            raise ValueError('retained cap budget exceeded')
        native_popen = e.subprocess.Popen
        def popen(argv, **kw):
            if len(argv) > 3 and argv[2] == str(ROOT / 'scripts/prism_bounded_eval.py'):
                argv = [argv[0], '-B', str(Path(__file__).resolve()), 'grid', argv[-1]]
            return native_popen(argv, **kw)
        e.subprocess.Popen = popen
        try:
            return complete + native_dispatch(pending, limit=limit, truncation_limit=truncation_limit-caps)
        finally:
            e.subprocess.Popen = native_popen
    e.dispatch = dispatch
    native_extract = m.extract_bound
    def extract(archive, receipt, allowed):
        if receipt['policy_sha256'] != digest(m.REV / 'policy.json') or digest(archive) != receipt['sha256'] or Path(archive).stat().st_size != receipt['bytes']:
            raise ValueError('archive receipt drift')
        with zipfile.ZipFile(archive) as z:
            members = json.loads(z.read('transfer-manifest.json'))
            if set(z.namelist()) != set(members) | {'transfer-manifest.json'} or len(members) != receipt['members']:
                raise ValueError('archive member drift')
            for rel, h in members.items():
                path = Path(rel)
                if path.is_absolute() or '..' in path.parts or not allowed(rel) or hashlib.sha256(z.read(rel)).hexdigest() != h:
                    raise ValueError('unsafe or corrupt member')
                dest = ROOT / rel
                if dest.exists() and digest(dest) != h:
                    raise ValueError('conflicting retained import')
            for rel in members:
                dest = ROOT / rel
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True);dest.write_bytes(z.read(rel))
        return members
    m.extract_bound = extract
    native_zip = m.zip_members
    def zip_members(archive, files):
        if Path(archive).exists():
            with zipfile.ZipFile(archive) as z:
                members = json.loads(z.read('transfer-manifest.json'))
                expected = {f.relative_to(ROOT).as_posix(): digest(f) for f in set(files)}
                if members == expected and all(hashlib.sha256(z.read(k)).hexdigest() == h for k,h in members.items()):
                    return dict(sha256=digest(archive), bytes=Path(archive).stat().st_size, members=len(members), policy_sha256=digest(m.REV / 'policy.json'))
            archive_path(archive, 'unfinished-transfer')
        return native_zip(archive, files)
    m.zip_members = zip_members
    source = inspect.getsource(m.stage)
    target = 'str(Path(__file__).resolve())'
    if source.count(target) != 1:
        raise ValueError('r4 stage adapter target drift')
    namespace = dict(m.__dict__)
    exec(compile(source.replace(target, "str(ROOT/'reboot-resume-r7/recovery.py')"), __file__+'::stage', 'exec'), namespace)
    native_stage = namespace['stage']
    def stage(mode, cpu_left, node):
        out = m.REV / mode
        done = out / 'completion.json'
        if done.exists() and read(done)['state'] == 'PASS':
            if mode == 'early-development':
                saved = read(m.REV / 'early-development-completion.json')
                for shard in saved['shards']: b.inspect(Path(shard['output']))
            return read(done)['resources']['cpu_seconds']
        journal_path = ROOT / 'development/recovery-r7' / (mode + '-charges.json')
        journal = read(journal_path) if journal_path.exists() else []
        if out.exists():
            snapshot = read(out / 'status.json') if (out / 'status.json').exists() else {}
            counters = snapshot.get('resources', {})
            # Wall time since the last counter is a conservative CPU upper bound,
            # including offline time; no unknown consumption becomes free budget.
            old_cost = (read(done)['resources']['cpu_seconds'] if done.exists() else
                        min(cpu_left-sum(x['charged_cpu_seconds'] for x in journal),
                            counters.get('cpu_seconds', 0.) + max(0., time.time()-snapshot.get('observed_at', out.stat().st_mtime)) * (8 if node == 'dsw2' else 4)))
            preserved = archive_path(out, 'stage-' + mode)
            journal.append(dict(preserved=str(preserved), charged_cpu_seconds=old_cost, accounting='MEASURED_PLUS_OFFLINE_WALL_CPU_UPPER_BOUND', observed_at=time.time()))
            write(journal_path, journal)
            if mode == 'audit' and (ROOT / 'audits/a').exists(): archive_path(ROOT / 'audits/a', 'unfinished-audit')
            if mode == 'report' and (ROOT / 'analysis').exists():
                raise ValueError('partial published report requires isolated report recovery')
        charged = sum(x['charged_cpu_seconds'] for x in journal)
        if charged >= cpu_left: raise ValueError('interrupted stage CPU reservation exhausted')
        if mode == 'candidates' and (ROOT / 'candidate-registry.json').exists():
            reg = read(ROOT / 'candidate-registry.json')
            if reg['models']['a']['audit_sha256'] != digest(ROOT / 'audits/a/audit.json') or reg['models']['a']['sha256'] != digest(ROOT / 'campaigns/a/cycle-20-export/weights.json'):
                raise ValueError('retained candidate registry drift')
            out.mkdir();write(done, dict(state='PASS', resources=dict(cpu_seconds=charged, returncode=0, stop_reason=None), recovered=True));return charged
        # Native stage calls the new child entrypoint, without editing r4 bytes.
        used = native_stage(mode, cpu_left-charged, node)
        receipt = read(done);receipt['resources']['cpu_seconds'] += charged
        receipt['recovery_revision'] = 'reboot-resume-r7';receipt['prior_attempts'] = journal
        write(done, receipt)
        return used + charged
    m.stage = stage
    native_write = m.write
    def recorded_write(path, value):
        if Path(path) == ROOT / 'evaluation-completion.json':
            retries = len(list((ROOT / 'evaluation').glob('*/recovery-attempts/*/r6-interruption.json')))
            value = dict(value, infrastructure_retries=retries, recovery_policy_sha256=digest(REV / 'policy.json'))
        native_write(path, value)
    m.write = recorded_write
    native_load = m.load
    def load_bound(name, path):
        module = native_load(name, path)
        if name == 'r4_handoff':
            controller = module.controller
            def restored_controller():
                d, p = controller()
                def monitor(_):
                    receipt = read(ROOT / 'continuation-r2/train/completion.json')
                    complete = read(ROOT / 'campaigns/a/worker-completion.json')
                    if receipt['state'] != 'PASS' or complete['physical_attempts'] != 5120 or complete['cycle'] != 20 or digest(complete['weights']) != complete['weights_sha256']:
                        raise ValueError('final training receipt drift')
                    return receipt['resources']['cpu_seconds']
                d.monitor_training = monitor
                native_import = d.import_baseline
                def import_base():
                    if (ROOT / 'dual-node-r3/baseline-import.json').exists():
                        for s in read(ROOT / 'dual-node-r3/baseline-completion.json')['shards']: b.inspect(Path(s['output']))
                        return None
                    return native_import()
                d.import_baseline = import_base
                return d, p
            module.controller = restored_controller
        return module
    m.load = load_bound


def run(token):
    p = contract()
    os.sched_setaffinity(0, range(8 if p['role'] == 'dsw2' else 4))
    m = load('m75_r6_r4', ROOT / 'eval-handoff-r4/controller.py');m.policy()
    m.TOKEN = token;install_adapters(m)
    try:
        m.run(p['role'])
    except BaseException as error:
        # Exception text can contain credentials from third-party transports.
        write(REV / 'failure.json', dict(state='FAILED', error_type=type(error).__name__, observed_at=time.time()))
        raise


def ensure(token=None):
    state = status()
    if state['state'] in ('RUNNING', 'IDLE_WAIT', 'COMPLETED', 'DEADLINE'):
        return state
    with (REV / 'owner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = status()
        if state['state'] in ('RUNNING', 'IDLE_WAIT', 'COMPLETED', 'DEADLINE'):
            return state
        p = contract()
        r4_policy=read(ROOT/'eval-handoff-r4/policy.json')
        # Refuse overlap with surviving orphan arena/worker processes.
        for proc in psutil.process_iter(['pid', 'cmdline', 'status']):
            argv = proc.info['cmdline'] or []
            if proc.pid != os.getpid() and proc.info['status'] != psutil.STATUS_ZOMBIE and any(str(ROOT) in arg for arg in argv):
                if (proc.pid == r4_policy['old_coordinator_pid'] and proc.info['status'] == psutil.STATUS_STOPPED
                        and abs(proc.create_time()-r4_policy['old_coordinator_created'])<.01):
                    continue  # Explicitly held predecessor; never resume it.
                raise ValueError('execution process exists without verified coordinator')
        attempts = read(REV / 'attempts.json') if (REV / 'attempts.json').exists() else []
        if len(attempts) >= p['max_coordinator_restarts']:
            raise ValueError('finite coordinator restart allowance exhausted')
        if not token:
            from modelscope_hub import HubApi
            token = HubApi().legacy.token
        if not token: raise ValueError('credential broker unavailable')
        m = load('r6_preflight_r4', ROOT / 'eval-handoff-r4/controller.py');m.policy()
        if p['role'] == 'dsw2':
            os.sched_setaffinity(0, range(8));m.verify_arena()
        else:
            receipt = read(ROOT / 'continuation-r2/train/completion.json')
            if receipt['state'] != 'PASS': raise ValueError('training was not finalized; refuse warm start')
        # Admission and fork are serialized; the child inherits the lock until exit.
        child = os.fork()
        if child:
            record = dict(state='STARTED', pid=child, create_time=psutil.Process(child).create_time(),
                          hostname=os.uname().nodename, observed_at=time.time(), deadline=p['deadline'],
                          source_sha256=digest(__file__), policy_sha256=digest(REV / 'policy.json'))
            attempts.append(record);write(REV / 'attempts.json', attempts);write(REV / 'launch.json', record)
            return record
        os.setsid()
        log = os.open(REV / ('attempt-' + str(len(attempts)+1) + '.log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.dup2(log,1);os.dup2(log,2);os.dup2(os.open('/dev/null',os.O_RDONLY),0)
        try:run(token)
        except BaseException:os._exit(1)
        os._exit(0)


def endpoint():
    request = json.loads(sys.stdin.readline(32768))
    method = request['method']
    if method == 'status': return status()
    if method == 'ensure': return ensure(request.get('token'))
    if method == 'credential' and read(REV / 'policy.json')['role'] == 'dsw':
        contract()
        from modelscope_hub import HubApi
        token = HubApi().legacy.token
        if not token: raise ValueError('existing credential unavailable')
        return dict(token=token)
    raise ValueError('unsupported restricted endpoint operation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('mode', choices=['endpoint','ensure-local','child','grid']);parser.add_argument('stage', nargs='?');args=parser.parse_args()
    if args.mode == 'grid':resume_grid(args.stage)
    elif args.mode == 'child':
        contract();m=load('r6_child_r4', ROOT/'eval-handoff-r4/controller.py');install_adapters(m)
        if args.stage == 'audit':
            from scripts import prism_notebook_report as report
            native=report.interval
            report.interval=lambda rows,pure=False:training_interval(native,rows,pure)
        m.child(args.stage)
    else:
        try: result=endpoint() if args.mode == 'endpoint' else ensure();print(json.dumps(result))
        except Exception as error:print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__)));sys.exit(1)
