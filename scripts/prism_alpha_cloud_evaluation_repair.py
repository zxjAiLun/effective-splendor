"""Explicit two-interruption M59 execution amendment; requires owner approval.

The original controller, failed receipt, seeds, weights and statistical gates
remain immutable. Only the two identified partial directories may be archived.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_alpha_cloud_acceptance as old
from scripts.prism_cloud_storage_snapshot import storage_bytes

read, write, sha, require = old.read, old.write, old.sha, old.require


def partial_guard(work, incident):
    allowed = incident['interrupted_acceptance_games']
    require(len(allowed) == 2 and incident['completed_acceptance_commits'] == 1817, 'unexpected incident scope')
    for row in allowed:
        path = Path(row['path']).resolve()
        require(path.is_relative_to((work / 'acceptance/runs').resolve()), 'partial directory outside owned runs')
        require(read(path / 'game.json')['status'] == 'running', 'refuse archive of completed game')
        actual = {p.name: sha(p) for p in path.iterdir() if p.is_file()}
        require(actual == row['hashes'], 'partial artifact drift')
    return allowed


def usage(work):
    cg = Path('/sys/fs/cgroup') / next(line.split(':', 2)[2].strip().lstrip('/')
                                     for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0:'))
    require('prism-m59-evaluation-repair-' in str(cg), 'not inside owned repair service')
    require(int((cg / 'memory.max').read_text()) == 8589934592, 'repair memory ceiling not applied')
    quota, period = map(int, (cg / 'cpu.max').read_text().split())
    require(quota / period == 2, 'repair CPU quota not applied')
    cpu = dict(line.split() for line in (cg / 'cpu.stat').read_text().splitlines())
    return {'cpu_seconds': int(cpu['usage_usec']) / 1e6, 'storage_bytes': storage_bytes(work),
            'memory_peak_bytes': int((cg / 'memory.peak').read_text()),
            'memory_current_bytes': int((cg / 'memory.current').read_text()),
            'memory_events': dict((k, int(v)) for k, v in
                                  (line.split() for line in (cg / 'memory.events').read_text().splitlines())),
            'cgroup': str(cg)}


def stage_resume(project, work, execution, deadline, original_cpu):
    plan = read(work / 'acceptance/plan.json')
    queue, active, finished = [], [], 0
    for shard in plan['shards']:
        output = Path(shard['output'])
        if (output / 'completion.json').exists():
            require(read(output / 'completion.json')['result_sha256'] == sha(output / 'result.json'), 'completed shard drift')
            finished += shard['games']
        else:
            queue.append(shard)
    while queue or active:
        while queue and len(active) < 2:
            shard = queue.pop(0)
            # run_eval skips hash-verified completed games. The two partial
            # directories were archived under the explicit approval receipt.
            log = open(Path(shard['config']).with_suffix('.repair.log'), 'xb')
            p = subprocess.Popen([sys.executable, '-B', str(project / 'scripts/prism_ppo_fixed_eval.py'),
                                  '--config', shard['config'], '--output', shard['output']],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            active.append((p, log, shard))
        completed, running = finished, []
        for p, log, shard in active:
            code = p.poll()
            if code is not None:
                log.close()
                require(code == 0, 'repaired shard failed; no further retry')
                require(Path(shard['output'], 'completion.json').exists(), 'missing repaired completion')
                finished += shard['games']; completed += shard['games']
            else:
                progress = Path(shard['output']) / 'progress.json'
                if progress.exists():
                    completed += sum(x['status'] == 'completed' for x in read(progress)['games'].values())
                running.append((p, log, shard))
        active = running
        resource = usage(work)
        require(datetime.now(timezone.utc) < deadline, 'original evaluation deadline expired')
        require(resource['cpu_seconds'] + original_cpu < execution['cpu_seconds'], 'original cumulative CPU budget')
        require(resource['storage_bytes'] < execution['storage_bytes'], 'original storage budget')
        write(work / 'repair-status.json', {'state': 'ACCEPTANCE_RUNNING_UNDER_APPROVED_REPAIR',
            'timestamp': old.now(), 'stage_completed': completed, 'stage_total': 4096,
            'maximum_interrupted_game_retries': 2, 'resources': resource,
            'original_cpu_seconds': original_cpu, 'active_worker_pids': [p.pid for p, _, _ in active]})
        if queue or active:
            time.sleep(5)
    return plan


def run(project, proposal_sha, owner_authorization):
    require(owner_authorization.strip(), 'explicit owner authorization text required')
    work = project / 'evaluation'
    proposal_path = work / 'incident/repair-proposal.json'
    require(sha(proposal_path) == proposal_sha, 'repair proposal drift')
    proposal = read(proposal_path)
    require(proposal['status'] == 'PROPOSED_NOT_AUTHORIZED' and proposal['maximum_interrupted_game_retries'] == 2
            and proposal['maximum_physical_eval_attempts'] == 4482, 'repair finite scope')
    execution = read(work / 'execution.json')
    require(sha(work / 'execution.json') == proposal['original_execution_sha256'], 'original execution drift')
    old.verify(work, execution)
    incident_path = work / 'incident/result.json'
    require(sha(incident_path) == proposal['incident_result_sha256'], 'incident drift')
    incident = read(incident_path)
    allowed = partial_guard(work, incident)
    require(read(work / 'status.json') == incident['original_status'], 'original failed status drift')
    failure_time = datetime.fromisoformat(incident['original_status']['timestamp'])
    original_start = failure_time - timedelta(seconds=incident['original_status']['elapsed_wall_seconds'])
    deadline = original_start + timedelta(seconds=execution['wall_seconds'])
    require(datetime.now(timezone.utc) < deadline, 'original deadline already expired')
    usage(work)  # Resource ownership checked before archive or any match.
    fd = os.open(work / 'repair-once-only.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    approval = {'format': 'm59-approved-execution-repair-v1', 'timestamp': old.now(),
                'owner_authorization': owner_authorization, 'proposal_sha256': proposal_sha,
                'original_execution_sha256': proposal['original_execution_sha256'],
                'original_failure_preserved': True, 'source_sha256': sha(__file__),
                'storage_fix_sha256': sha(ROOT / 'scripts/prism_cloud_storage_snapshot.py'),
                'maximum_interrupted_game_retries': 2, 'maximum_physical_eval_attempts': 4482,
                'original_deadline': deadline.isoformat(), 'archived_partials': []}
    archive = work / 'incident/original-partials'
    archive.mkdir()
    for i, row in enumerate(allowed):
        path, target = Path(row['path']).resolve(), archive / f'partial-{i}'
        require(not target.exists(), 'partial archive exists')
        path.rename(target)
        approval['archived_partials'].append({'original_path': str(path), 'archive': str(target),
                                             'hashes': row['hashes']})
    write(work / 'repair-approval.json', approval)
    started = time.monotonic()
    try:
        plan = stage_resume(project, work, execution, deadline, incident['cpu_seconds'])
        comparisons = []
        for row in approval['archived_partials']:
            archive_replay = Path(row['archive']) / 'replay.json'
            if archive_replay.exists():
                before, after = read(archive_replay), read(Path(row['original_path']) / 'replay.json')
                require(before['result'] == after['result'], 'terminal interrupted result differs on bounded replay')
                require([(x['actor'], x['action']) for x in before['steps']] ==
                        [(x['actor'], x['action']) for x in after['steps']], 'terminal interrupted actions differ')
                comparisons.append({'archive': row['archive'], 'same_result_and_actions': True})
        pilot, train, _ = old.bindings(project)
        old.alpha.ART, old.alpha.ROOT = work, work / 'collector-root'
        old.alpha.ANCHORS = tuple(pilot['evaluation']['acceptance']['anchors'])
        old.alpha.DISPLAY = old.DISPLAY
        eval_train = copy.deepcopy(train)
        eval_train['opponents']['prism-general-v011']['hello'] = {'agent_name': 'prism-sample', 'agent_version': '0.1.0'}
        rows, pairs = old.alpha.collect(plan, pilot['evaluation'], eval_train)
        result = read(work / 'result.json')
        write(work / 'incident/pre-repair-evaluation-result.json', result)
        result['acceptance'] = {'games': len(rows), 'pairs': pairs,
            'match_details_sha256': sha(work / 'acceptance/match-details.json'),
            'source_ledger_sha256': sha(work / 'acceptance/source-ledger.json'),
            'style_metrics_sha256': sha(work / 'acceptance/style-metrics.json'),
            'plan_sha256': sha(work / 'acceptance/plan.json')}
        result['measurements'], result['gates'] = old.alpha.measurements(rows, pilot['evaluation']['acceptance'])
        result['all_three_gates_passed'] = all(result['gates'].values())
        result['independent_strength_acceptance'] = 'PASS' if result['all_three_gates_passed'] else 'FAIL'
        result['status'] = 'ACCEPTED_BIGCARD_CONTINUATION' if result['all_three_gates_passed'] else 'NOT_ACCEPTED_BIGCARD_CONTINUATION'
        result['finished_at'] = old.now()
        result['elapsed_wall_seconds'] = (datetime.now(timezone.utc) - original_start).total_seconds()
        result['repair_active_wall_seconds'] = time.monotonic() - started
        result['resources'] = usage(work)
        result['resources']['cpu_seconds'] += incident['cpu_seconds']
        result['resources']['memory_peak_bytes'] = max(result['resources']['memory_peak_bytes'], incident['memory_peak_bytes'])
        result['execution_repair'] = {'approval_sha256': sha(work / 'repair-approval.json'),
            'proposal_sha256': proposal_sha, 'original_failure_preserved': True,
            'infrastructure_interrupted_game_retries': 2, 'logical_eval_games': 4480,
            'physical_eval_attempts': 4482, 'terminal_orphan_comparisons': comparisons,
            'formal_gates_analyzed_once': True, 'original_failed_status': incident['original_status']}
        old.verify(work, execution)
        write(work / 'result.json', result)
        completion = {'status': result['status'], 'timestamp': old.now(), 'result_sha256': sha(work / 'result.json'),
                      'logical_eval_games': 4480, 'physical_eval_attempts': 4482,
                      'interrupted_game_retries': 2, 'formal_gates_analyzed_once': True}
        write(work / 'completion.json', completion)
        write(work / 'repair-status.json', completion)
    except BaseException as exc:
        # Exit from the owning systemd service kills its whole control group.
        write(work / 'repair-status.json', {'state': 'FAILED_NO_FURTHER_RETRY', 'timestamp': old.now(), 'error': str(exc)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--proposal-sha256', required=True)
    parser.add_argument('--owner-authorization', required=True)
    args = parser.parse_args()
    run(args.project.resolve(), args.proposal_sha256, args.owner_authorization)
