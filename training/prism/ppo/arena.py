"""Bounded synchronous live Arena launcher (CPU, Windows, trusted local files)."""
import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

from ..io import canonical_hash, read_json, sha256_file, write_json
from .audit import bounded_json
from .coordinator import Run
from .execution import absolute, arena_config, check_assets, validate_spec, verify_completion, verify_report
from .processes import ProcessTree, directory_bytes
from .sampling import Behavior
from .service import BehaviorServer
from .store import CommitStore

# Only transport/time/process infrastructure may retry. Malformed/illegal
# actions, identity/protocol mismatches, truncation and audit failures are fatal.
INFRA_FAULTS = {'handshake_timeout', 'action_timeout', 'agent_eof', 'agent_io'}


class Campaign:
    def __init__(self, root, spec):
        self.root = Path(root).resolve()
        self.spec = validate_spec(spec)
        self.run = Run.open(self.root / 'run')
        if self.run.config != spec['run']:
            raise ValueError('campaign/run identity mismatch')
        self.ledger = CommitStore(self.root / 'launch-ledger', spec['run']['arena_contract_sha256'])
        self._ledger_cache = None

    @classmethod
    def create(cls, root, spec):
        validate_spec(spec); check_assets(spec)
        root = Path(root).resolve()
        if root.exists():
            raise ValueError('new campaign directory must not exist')
        root.mkdir(parents=True)
        write_json(root / 'contract.json', spec)
        Run.create(root / 'run', spec['run'], spec['parent_weights'])
        campaign = cls(root, spec)
        with campaign.ledger.lock():
            campaign.ledger.commit({'format': 'prism-ppo-launch-ledger-v1', 'attempts': {},
                                    'physical_decisions': 0, 'retries': 0, 'failed': False,
                                    'recoveries': []}, expected_parent=None)
        return campaign

    def _load(self):
        if self._ledger_cache is None or self.ledger.head() != self._ledger_cache[0]:
            self._ledger_cache = self.ledger.load()
        head, state = self._ledger_cache
        if state is None or state['format'] != 'prism-ppo-launch-ledger-v1':
            raise ValueError('missing launcher ledger')
        return head, state

    def record(self, number, data, *, decisions=0, retry=False, failed=False):
        with self.ledger.lock():
            head, state = self._load()
            state = copy.deepcopy(state)
            previous = state['attempts'].get(str(number), {})
            charged = max(decisions, previous.get('charged_decisions', 0))
            retry_charged = retry or previous.get('retry_charged', False)
            state['attempts'][str(number)] = dict(data, charged_decisions=charged, retry_charged=retry_charged)
            state['physical_decisions'] += charged - previous.get('charged_decisions', 0)
            state['retries'] += int(retry_charged) - int(previous.get('retry_charged', False))
            state['failed'] |= failed
            if state['physical_decisions'] > self.spec['limits']['max_physical_decisions']:
                raise ValueError('physical decision budget exhausted')
            self._ledger_cache = (self.ledger.commit(state, expected_parent=head), state)

    def fail(self, job, error):
        with self.ledger.lock():
            head, state = self._load()
            state = copy.deepcopy(state)
            state['failed'] = True
            state['recoveries'].append({'job_id': job['job_id'], 'event': 'fatal', 'error_type': type(error).__name__})
            self._ledger_cache = (self.ledger.commit(state, expected_parent=head), state)
        self.run.pause()

    def _paths(self, number):
        directory = self.root / 'attempts' / f'{number:03d}'
        return directory, directory / 'completion.json', directory / 'replay.json', directory / 'sidecar.jsonl'

    def recover_running(self, job, snapshot):
        state = self.run.status()['jobs'].get(job['job_id'])
        if not state or state['status'] == 'COMPLETE':
            return
        number = state['attempt']
        directory, completion, replay, sidecar = self._paths(number)
        # Crash after completion publication but before submit: consume exactly
        # the existing package, never launch a replacement completed game.
        if completion.exists():
            verify_completion(self.run.config, job, number, completion, replay=replay, sidecar=sidecar,
                              behavior_id=snapshot['behavior_id'])
            with sidecar.open('rb') as stream:
                count = sum(1 for _ in stream)
            self.record(number, {'job': job, 'status': 'PUBLISHED'}, decisions=count)
            self.run.submit(job['job_id'], number, executable=self.spec['arena']['program'],
                            replay=replay, sidecar=sidecar, completion=completion)
            self.record(number, {'job': job, 'status': 'COMPLETE', 'completion_sha256': sha256_file(completion)})
            return
        if (directory / 'report.json').exists():
            report = bounded_json(directory / 'report.json')
            if report['outcome']['status'] in ('completed', 'truncated'):
                raise ValueError('published terminal/cap without completion package; retain and stop, never replay')
        _, ledger = self._load()
        previous = ledger['attempts'].get(str(number))
        if previous and previous['status'] == 'INFRA_ABORT':
            return
        if previous and previous['status'] == 'FATAL':
            raise ValueError('failed attempt cannot be retried')
        # Unknown physical work is charged the full decision reservation. Never
        # guess zero because a sidecar/report wasn't published before a crash.
        self.record(number, {'job': job, 'status': 'INFRA_ABORT', 'reason': 'interrupted_unpublished'},
                    decisions=self.spec['run']['budget']['max_job_decisions'], retry=True)

    @contextmanager
    def service(self, snapshot):
        behavior = Behavior.from_payload(self.run.store.get_payload(snapshot['snapshot_sha256']), runtime=self.run.runtime)
        token = secrets.token_hex(32)
        with BehaviorServer(('127.0.0.1', 0), behavior, token) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f'127.0.0.1:{server.server_address[1]}', token
            finally:
                server.shutdown(); thread.join(timeout=35)
                if thread.is_alive():
                    raise RuntimeError('behavior server did not stop')

    def launch(self, job, snapshot, endpoint, token):
        _, ledger = self._load()
        started = time.perf_counter()
        if ledger['failed'] or ledger['retries'] > self.spec['limits']['max_infra_retries']:
            raise ValueError('launcher failed/retry budget exhausted')
        maximum = self.spec['run']['budget']['max_job_decisions']
        if ledger['physical_decisions'] + maximum > self.spec['limits']['max_physical_decisions']:
            raise ValueError('physical decision reservation exhausted')
        if directory_bytes(self.root) + 64 * 1024**2 > self.spec['run']['budget']['max_storage_bytes']:
            raise ValueError('insufficient artifact storage reservation')
        check_assets(self.spec)
        number = self.run.start_attempt(job['job_id'])  # persisted before spawn
        directory, completion, replay, sidecar = self._paths(number)
        directory.mkdir(parents=True, exist_ok=False)
        config = arena_config(self.spec, job, snapshot['behavior_id'], endpoint, sidecar)
        write_json(directory / 'arena-config.json', config)
        live_config = copy.deepcopy(config)
        live_config['agents'][job['actor']]['args'][4] = token
        # The actual configuration exists only while the owned process runs.
        # It is replaced by the redacted equivalent before any package commits.
        write_json(directory / 'arena-config.json', live_config)
        argv = [absolute(self.spec['arena']['program']), 'run-rollout', '--config', str(directory / 'arena-config.json'),
                '--max-plies', str(self.spec['limits']['max_plies']), '--report-out', str(directory / 'report.json'),
                '--replay-out', str(replay), '--prefix-out', str(directory / 'prefix.json')]
        self.record(number, {'job': job, 'status': 'RUNNING', 'argv': argv, 'arena_config': config})
        resources, pid = None, None
        try:
            with (directory / 'stdout.log').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
                with ProcessTree(cpu_seconds=self.spec['limits']['game_cpu_seconds'],
                                 memory_bytes=self.spec['limits']['memory_bytes']) as tree:
                    process = tree.start(argv, cwd=absolute('.'), stdout=out, stderr=err)
                    pid = process.pid
                    self.record(number, {'job': job, 'status': 'RUNNING', 'argv': argv,
                                         'arena_config': config, 'pid': pid})
                    resources = tree.wait(wall_seconds=self.spec['limits']['game_wall_seconds'],
                                          storage_root=self.root,
                                          max_storage_bytes=self.spec['run']['budget']['max_storage_bytes'])
        except (OSError, RuntimeError) as exc:
            resources = {'returncode': -1, 'stop_reason': 'spawn_infrastructure', 'error_type': type(exc).__name__}
        finally:
            write_json(directory / 'arena-config.json', config)
        count = 0
        if sidecar.exists():
            with sidecar.open('rb') as stream:
                count = sum(1 for _ in stream)
        if count > maximum:
            raise ValueError('physical job decision limit exceeded')
        self.record(number, {'job': job, 'status': 'FINISHED_PENDING_AUDIT', 'resources': resources,
                             'decisions': count}, decisions=count)
        check_assets(self.spec)
        write_json(directory / 'process-result.json', resources)
        report_path = directory / 'report.json'
        outcome = None
        if report_path.exists():
            report = bounded_json(report_path)
            outcome = verify_report(self.spec, job, report, bounded_json(replay) if replay.exists() else None)
        if resources['returncode'] == 0 and resources['stop_reason'] is None and outcome and outcome['status'] == 'completed':
            package = {'format': 'prism-ppo-arena-completion-v1', 'contract': self.spec, 'job': job,
                       'attempt': number, 'behavior_id': snapshot['behavior_id'],
                       'snapshot_sha256': snapshot['snapshot_sha256'], 'endpoint': endpoint, 'cwd': absolute('.'),
                       'arena_config': config, 'arena_argv': argv, 'pid': pid, 'resources': resources,
                       'files': {name: {'path': str(path), 'sha256': sha256_file(path)} for name, path in
                                 [('report', report_path), ('replay', replay), ('sidecar', sidecar)]}}
            write_json(completion, package)
            verify_completion(self.run.config, job, number, completion, replay=replay, sidecar=sidecar,
                              behavior_id=snapshot['behavior_id'])
            # Charge physical work before ingestion so a later audit failure is
            # still costed. Recovery sees the immutable completed package.
            self.record(number, {'job': job, 'status': 'PUBLISHED', 'decisions': count}, decisions=count)
            ingest_started = time.perf_counter()
            self.run.submit(job['job_id'], number, executable=self.spec['arena']['program'],
                            replay=replay, sidecar=sidecar, completion=completion)
            ingest_seconds = time.perf_counter() - ingest_started
            self.record(number, {'job': job, 'status': 'COMPLETE', 'completion_sha256': sha256_file(completion),
                                 'game_wall_seconds': resources['wall_seconds'], 'ingest_seconds': ingest_seconds,
                                 'launch_seconds': time.perf_counter() - started})
            print(json.dumps({'event': 'game_complete', 'job_id': job['job_id'], 'attempt': number,
                              'decisions': count, 'result': outcome['result'],
                              'launch_seconds': time.perf_counter() - started,
                              'game_wall_seconds': resources['wall_seconds'], 'ingest_seconds': ingest_seconds}), flush=True)
            return True
        infrastructure = (outcome is not None and outcome['status'] == 'aborted' and outcome['reason'] in INFRA_FAULTS)
        infrastructure |= outcome is None and resources['stop_reason'] == 'spawn_infrastructure'
        # Hard deadlines, cap and any deterministic protocol/identity defect are
        # fatal rather than "infrastructure" replacement-game opportunities.
        self.record(number, {'job': job, 'status': 'INFRA_ABORT' if infrastructure else 'FATAL',
                             'resources': resources, 'outcome': outcome, 'decisions': count},
                    decisions=count, retry=infrastructure, failed=not infrastructure)
        if not infrastructure:
            raise ValueError('Arena truncation/deadline/protocol failure; campaign stopped')
        _, ledger = self._load()
        if ledger['retries'] > self.spec['limits']['max_infra_retries']:
            raise ValueError('infrastructure retry budget exhausted')
        return False

    def work(self, *, stop_after_cycle=False):
        # Separate campaign lock protects dispatch; Run's shorter lock protects
        # its individual commits. Two launchers may not dispatch the same job.
        dispatcher = CommitStore(self.root / 'dispatcher', self.run.identity)
        with dispatcher.lock():
            _, ledger = self._load()
            if ledger['failed']:
                raise ValueError('fatal campaign cannot resume')
            while True:
                status = self.run.status()
                if status['paused']:
                    raise ValueError('campaign paused; explicit resume required')
                if status['phase'] in ('READY', 'COMMITTED'):
                    if status['cycle'] == len(self.spec['cycles']):
                        return
                    snapshot = self.run.begin_cycle(self.spec['cycles'][status['cycle']])
                else:
                    if status['phase'] == 'FAILED':
                        raise ValueError('run failed')
                    digest = self.run.state['snapshot']
                    behavior = Behavior.from_payload(self.run.store.get_payload(digest), runtime=self.run.runtime)
                    snapshot = {'behavior_id': behavior.identity, 'snapshot_sha256': digest}
                status = self.run.status()
                if status['phase'] == 'COLLECTING':
                    with self.service(snapshot) as (endpoint, token):
                        for job in self.spec['cycles'][status['cycle'] - 1]:
                            try:
                                self.recover_running(job, snapshot)
                                while self.run.status()['jobs'].get(job['job_id'], {}).get('status') != 'COMPLETE':
                                    if self.launch(job, snapshot, endpoint, token):
                                        break
                            except BaseException as exc:
                                self.fail(job, exc)
                                raise
                    seal_started = time.perf_counter()
                    self.run.seal()
                    print(json.dumps({'event': 'batch_sealed', 'cycle': status['cycle'],
                                      'seconds': time.perf_counter() - seal_started}), flush=True)
                update_started = time.perf_counter()
                # Tail minibatches stay within each saved pass; committed steps
                # are never replayed when this launcher is reopened.
                while self.run.status()['phase'] == 'UPDATING':
                    metrics = self.run.step()
                    print(json.dumps({'event': 'optimizer_step', 'cycle': self.run.state['cycle'],
                                      'global_step': self.run.state['global_step'], 'metrics': metrics}), flush=True)
                summary = self.cycle_summary()
                summary['this_session_update_seconds'] = time.perf_counter() - update_started
                write_json(self.root / f'cycle-{self.run.state["cycle"]}-summary.json', summary)
                print(json.dumps(dict(summary, event='cycle_committed')), flush=True)
                export = self.root / f'cycle-{self.run.status()["cycle"]}-export'
                if not export.exists():
                    self.run.export(export)
                if stop_after_cycle:
                    return

    def cycle_summary(self):
        cycle = self.run.state['cycle']
        groups = {}
        for job in self.spec['cycles'][cycle - 1]:
            record = self.run.state['jobs'][job['job_id']]
            if record['status'] != 'COMPLETE':
                raise ValueError('cannot summarize incomplete cycle')
            shard = self.run.store.get_json(record['artifact'])
            ranks = shard['result']['ranks']
            actor = job['actor']
            score = 0.5 if ranks[0] == ranks[1] else float(ranks[actor] < ranks[1-actor])
            for key in ('all', job['opponent_id'], f'{job["opponent_id"]}/seat{actor}'):
                group = groups.setdefault(key, {'games': 0, 'wins': 0, 'draws': 0, 'losses': 0,
                                                'reward_sum': 0.0, 'decisions': 0})
                group['games'] += 1; group['reward_sum'] += score
                group['wins' if score == 1 else 'draws' if score == 0.5 else 'losses'] += 1
                group['decisions'] += len(shard['decisions'])
        for group in groups.values():
            group['mean_reward'] = group['reward_sum'] / group['games']
        updates = [m for m in self.run.state['metrics'] if m.get('cycle') == cycle and
                   m.get('event') in ('optimizer_step', 'optimizer_diagnostic')]
        reason = next(m['event'] for m in reversed(self.run.state['metrics']) if
                      m.get('cycle') == cycle and m['event'] in ('passes_complete', 'kl_stop'))
        _, ledger = self._load()
        attempts = [a for a in ledger['attempts'].values() if a.get('job', {}).get('job_id') in self.run.state['jobs']]
        return {'format': 'prism-ppo-cycle-summary-v1', 'cycle': cycle, 'training_only': True,
                'groups': groups, 'optimizer_steps': sum(m['optimizer_applied'] for m in updates),
                'update_attempts': sum(m.get('event') == 'optimizer_attempt' and m.get('cycle') == cycle
                                       for m in self.run.state['metrics']),
                'stop_reason': reason, 'updates': updates,
                'game_wall_seconds': sum(a.get('game_wall_seconds', 0) for a in attempts),
                'ingest_seconds': sum(a.get('ingest_seconds', 0) for a in attempts),
                'launch_seconds': sum(a.get('launch_seconds', 0) for a in attempts)}


def supervised(root, *, stop_after_cycle):
    root = Path(root).resolve()
    spec = validate_spec(read_json(root / 'contract.json'))
    run = Run.open(root / 'run')
    elapsed = time.time() - run.state['started_at']
    remaining_wall = spec['run']['budget']['max_run_seconds'] - elapsed
    sessions_path = root / 'supervisor-sessions.json'
    sessions = read_json(sessions_path) if sessions_path.exists() else []
    spent = sum(s.get('user_cpu_seconds', s['cpu_reservation']) for s in sessions)
    remaining_cpu = spec['limits']['campaign_cpu_seconds'] - spent
    if remaining_wall <= 0 or remaining_cpu <= 0:
        raise ValueError('campaign CPU/wall budget exhausted')
    # Persist reservation before starting the owned worker. If this supervisor
    # itself dies, unknown CPU is charged conservatively on next invocation.
    record = {'cpu_reservation': remaining_cpu, 'status': 'RUNNING'}
    sessions.append(record); write_json(sessions_path, sessions)
    argv = [sys.executable, '-B', '-m', 'training.prism.ppo.arena', '--campaign', str(root), '--worker']
    if stop_after_cycle:
        argv.append('--stop-after-cycle')
    with ProcessTree(cpu_seconds=remaining_cpu, memory_bytes=spec['limits']['memory_bytes'], max_processes=6) as tree:
        tree.start(argv, cwd=absolute('.'), stdout=None, stderr=None)
        resources = tree.wait(wall_seconds=remaining_wall, storage_root=root,
                              max_storage_bytes=spec['run']['budget']['max_storage_bytes'])
    record.update(resources, status='FINISHED'); write_json(sessions_path, sessions)
    if resources['returncode'] != 0 or resources['stop_reason'] is not None:
        raise RuntimeError('supervised campaign stopped; retained artifacts must be inspected')
    return resources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--contract', help='create a new campaign using this frozen JSON')
    parser.add_argument('--stop-after-cycle', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.contract:
        Campaign.create(args.campaign, read_json(args.contract))
    if args.worker:
        Campaign(args.campaign, read_json(Path(args.campaign) / 'contract.json')).work(stop_after_cycle=args.stop_after_cycle)
    else:
        supervised(args.campaign, stop_after_cycle=args.stop_after_cycle)


if __name__ == '__main__':
    main()
