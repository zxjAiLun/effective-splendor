"""Offline, model-oriented metrics from completed Prism paired-seat evaluations.

Never invokes an agent or run-match. The Rust metrics utility verifies/reconstructs
replays; split by candidate identity AND seat before merging physical seat metrics.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import numpy as np

ACTIONS = ('buy_market', 'buy_reserved', 'take_tokens', 'reserve_market',
           'reserve_deck', 'choose_noble', 'pass')
COLORS = ('White', 'Blue', 'Green', 'Red', 'Black')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def score_ci(rows):
    paired = defaultdict(dict)
    for row in rows:
        paired[row['seed']][row['candidate_seat']] = row['candidate_score']
    require(all(set(x) == {0, 1} for x in paired.values()), 'incomplete dual-seat block')
    blocks = np.array([(paired[s][0] + paired[s][1]) / 2 for s in sorted(paired)])
    rng = np.random.default_rng(54049999)
    samples = np.concatenate([blocks[rng.integers(0, len(blocks), (1000, len(blocks)))].mean(1)
                              for _ in range(20)])
    return {'mean': float(blocks.mean()), 'ordinary_95_ci': np.quantile(samples, [.025, .975]).tolist(),
            'kind': 'descriptive per-pair paired-seed bootstrap; not an added acceptance gate',
            'resamples': 20000, 'rng_seed': 54049999}


def merge_player(batches, rows, candidate):
    n = len(rows)
    out = {'games': n}
    for key in ('wins', 'ties', 'losses', 'games_with_nobles'):
        out[key] = sum(m[key] for m, _ in batches)
    for key in ('mean_prestige', 'mean_nobles', 'mean_permanent_bonuses',
                'mean_reserves_acquired', 'mean_reserves_bought', 'mean_reserves_stranded'):
        out[key] = sum(m[key] * count for m, count in batches) / n
    for key, members in (('mean_cards_by_vp', tuple(map(str, range(6)))),
                         ('mean_bonuses_by_color', COLORS)):
        out[key] = {member: sum(m[key].get(member, 0) * count for m, count in batches) / n
                    for member in members}
    counts = {a: sum(m['action_distribution'].get(a, 0) for m, _ in batches) for a in ACTIONS}
    out['action_distribution'] = counts
    total_actions = sum(counts.values())
    raw_actions = Counter()
    for row in rows:
        raw_actions.update(row['_candidate_actions' if candidate else '_opponent_actions'])
    require(counts == {a: raw_actions[a] for a in ACTIONS}, 'model-oriented action counts mismatch')
    raw_points = sum(row['candidate_points' if candidate else 'opponent_points'] for row in rows)
    require(math.isclose(out['mean_prestige'], raw_points / n, abs_tol=1e-9), 'score identity mismatch')
    wins = sum(row['record'] == ('win' if candidate else 'loss') for row in rows)
    draws = sum(row['record'] == 'draw' for row in rows)
    require((out['wins'], out['ties'], out['losses']) == (wins, draws, n - wins - draws), 'seat outcome mixing')
    require(math.isclose(sum(out['mean_cards_by_vp'].values()), out['mean_permanent_bonuses'], abs_tol=1e-9),
            'purchased card / discount conservation failure')
    require(math.isclose(out['mean_permanent_bonuses'], (counts['buy_market'] + counts['buy_reserved']) / n,
                         abs_tol=1e-9), 'buy action / card conservation failure')
    require(math.isclose(sum(int(k) * v for k, v in out['mean_cards_by_vp'].items()) + 3 * out['mean_nobles'],
                         out['mean_prestige'], abs_tol=1e-9), 'card VP / noble / prestige conservation failure')
    require(math.isclose(out['mean_reserves_acquired'], (counts['reserve_market'] + counts['reserve_deck']) / n,
                         abs_tol=1e-9), 'reserve acquisition mismatch')
    require(math.isclose(out['mean_reserves_bought'], counts['buy_reserved'] / n, abs_tol=1e-9), 'reserve purchase mismatch')
    require(math.isclose(out['mean_reserves_stranded'], out['mean_reserves_acquired'] - out['mean_reserves_bought'],
                         abs_tol=1e-9), 'reserve conservation failure')
    out.update(win_rate_percent=100 * wins / n, score_rate=(wins + .5 * draws) / n,
               games_with_nobles_percent=100 * out['games_with_nobles'] / n,
               total_actor_decisions=total_actions,
               total_main_actions=total_actions - counts['choose_noble'],
               vp_per_turn=raw_points / total_actions,
               vp_per_main_action=raw_points / (total_actions - counts['choose_noble']),
               vp_per_ply=raw_points / sum(row['plies'] for row in rows),
               reserve_redemption_rate_percent=(100 * out['mean_reserves_bought'] / out['mean_reserves_acquired']
                                               if out['mean_reserves_acquired'] else None),
               action_percentages={a: 100 * counts[a] / total_actions for a in ACTIONS})
    return out


def macro(rows):
    plies = [r['plies'] for r in rows]
    turns = [(p + 1) // 2 for p in plies]
    main_rounds = [(sum(r['_candidate_actions'].values()) + sum(r['_opponent_actions'].values())
                    - r['_candidate_actions']['choose_noble'] - r['_opponent_actions']['choose_noble'] + 1) // 2
                   for r in rows]
    wall = [r['_wall_seconds'] for r in rows]
    return dict(total_games=len(rows), total_plies=sum(plies), mean_plies=statistics.mean(plies),
                mean_turns=statistics.mean(turns), min_turns=min(turns), max_turns=max(turns),
                median_turns=statistics.median(turns), std_turns=statistics.pstdev(turns),
                mean_main_rounds=statistics.mean(main_rounds),
                mean_victory_margin=statistics.mean(abs(r['candidate_points'] - r['opponent_points']) for r in rows),
                close_games_margin_le_2_percent=100 * sum(abs(r['candidate_points'] - r['opponent_points']) <= 2
                                                         for r in rows) / len(rows),
                process_wall_seconds_sum=sum(wall), process_wall_seconds_mean=statistics.mean(wall),
                process_wall_seconds_p95=float(np.quantile(wall, .95)),
                decision_latency_ms=None, inference_latency_ms=None,
                missing_latency_reason='per-decision/inference timings were not recorded in these reports')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--acceptance-result', type=Path, required=True)
    ap.add_argument('--metrics-program', type=Path, required=True)
    ap.add_argument('--work-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    plan = read(args.plan)
    require(sha(plan['contract_path']) == plan['contract_sha256'], 'frozen contract drift')
    groups = defaultdict(list)
    ledger = []
    for shard in plan['shards']:
        require(sha(shard['config']) == shard['config_sha256'], 'shard config drift')
        out = Path(shard['output'])
        progress = read(out / 'progress.json')
        require(progress['config_sha256'] == canonical_sha(read(shard['config']))
                == canonical_sha(read(out / 'config.json')), 'progress binding drift')
        for record in progress['games'].values():
            require(record['status'] == 'completed', 'non-completed match')
            row = dict(record['row'])
            path = out / 'games' / row['candidate'] / row['opponent'] / f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            g = read(path / 'game.json')
            require(g['row'] == record['row'] and g['status'] == 'completed', 'record disagreement')
            hashes = {name: sha(path / name) for name in ('report.json', 'replay.json', 'process-result.json', 'match-config.json')}
            require(hashes['report.json'] == record['report_sha256'] == g['report_sha256'], 'report hash drift')
            require(hashes['replay.json'] == record['replay_sha256'] == g['replay_sha256'], 'replay hash drift')
            require(canonical_sha(read(path / 'match-config.json')) == g['game_config_sha256'], 'match config drift')
            replay, report, process = (read(path / name) for name in ('replay.json', 'report.json', 'process-result.json'))
            require(process['returncode'] == 0 and process['wall_seconds'] > 0, 'invalid process timing/status')
            require(report['outcome']['status'] == 'completed' and replay['seed'] == row['seed'], 'terminal/seed mismatch')
            require(report['outcome']['result'] == replay['result'], 'terminal result mismatch')
            require(len(replay['steps']) == row['plies'] == report['outcome']['completed_plies'], 'ply mismatch')
            require(replay['result']['scores'] == row['scores'] and replay['result']['winners'] == row['winners'], 'outcome mismatch')
            row['_candidate_actions'], row['_opponent_actions'] = Counter(), Counter()
            for step in replay['steps']:
                row['_candidate_actions' if step['actor'] == row['candidate_seat'] else '_opponent_actions'][step['action']['type']] += 1
            row['_wall_seconds'] = process['wall_seconds']
            row['_replay_path'] = str((path / 'replay.json').resolve())
            groups[(row['candidate'], row['opponent'], row['candidate_seat'])].append(row)
            ledger.append({'game': str(path / 'game.json'), 'hashes': hashes})
    require(len(ledger) == 5120 and len(groups) == 10, 'unexpected full grid size')
    for key, rows in groups.items():
        require(len(rows) == 512 and {r['seed'] for r in rows} == set(range(9470000, 9470512)), f'grid mismatch {key}')
    write(args.work_dir / 'source-ledger.json', ledger)
    metrics, receipts = {}, []
    for key, rows in sorted(groups.items()):
        label = '-'.join(map(str, key))
        manifest, output = args.work_dir / (label + '.manifest.json'), args.work_dir / (label + '.metrics.json')
        write(manifest, {'rows': [{'replay_path': r['_replay_path']} for r in sorted(rows, key=lambda r: r['seed'])]})
        cmd = [str(args.metrics_program.resolve()), str(manifest.resolve()), str(output.resolve())]
        start = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        receipt = dict(argv=cmd, exit_code=result.returncode, wall_seconds=time.perf_counter() - start,
                       stdout=result.stdout, stderr=result.stderr, manifest_sha256=sha(manifest))
        write(args.work_dir / (label + '.receipt.json'), receipt)
        require(result.returncode == 0, f'Rust replay verification failed: {label}: {result.stderr}')
        metrics[key] = read(output)
        receipts.append(dict(label=label, metrics_sha256=sha(output), receipt_sha256=sha(args.work_dir / (label + '.receipt.json'))))
        print(f'verified {label}: {len(rows)} saved replays', flush=True)
    pairs = []
    accepted = read(args.acceptance_result)
    for model, opponent in sorted({(k[0], k[1]) for k in groups}):
        rows = groups[(model, opponent, 0)] + groups[(model, opponent, 1)]
        candidate_batches, opponent_batches, seats = [], [], []
        for seat in (0, 1):
            m, seat_rows = metrics[(model, opponent, seat)], groups[(model, opponent, seat)]
            cand, opp = m['seat_p0_first' if seat == 0 else 'seat_p1_second'], m['seat_p1_second' if seat == 0 else 'seat_p0_first']
            candidate_batches.append((cand, len(seat_rows)))
            opponent_batches.append((opp, len(seat_rows)))
            seats.append(dict(candidate_seat=seat, candidate=merge_player([(cand, len(seat_rows))], seat_rows, True),
                              opponent=merge_player([(opp, len(seat_rows))], seat_rows, False), macro=macro(seat_rows)))
        pair = dict(candidate=model, candidate_display=('Prism v0.1.1 (011)' if model == 'c8' else 'trial-v1 c8 parent'),
                    opponent=opponent, candidate_metrics=merge_player(candidate_batches, rows, True),
                    opponent_metrics=merge_player(opponent_batches, rows, False),
                    macro=macro(rows), seats=seats, score_uncertainty=score_ci(rows))
        expected = accepted['direct_duel_wdl'] if opponent == 'parent-t1' else accepted['anchor_results'][model][opponent]
        if opponent == 'parent-t1':
            pair['score_uncertainty'] = {
                'mean': accepted['measurements']['direct_duel']['mean'],
                'ordinary_95_ci': accepted['measurements']['direct_duel']['ci95'],
                'kind': 'original frozen acceptance interval; unchanged RNG stream and formal measurements',
                'source': str(args.acceptance_result)}
        cm = pair['candidate_metrics']
        require((cm['wins'], cm['ties'], cm['losses']) == (expected['wins'], expected['draws'], expected['losses']), 'frozen acceptance WDL mismatch')
        require(cm['score_rate'] == expected['score_rate'], 'frozen acceptance score mismatch')
        pairs.append(pair)
    write(args.output, dict(format='prism-model-match-details-v1', model_version='prism-v0.1.1', model_code='011',
                            status='VERIFIED_OFFLINE_REPLAY_METRICS', baseline_commit='bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57',
                            new_games=0, training_updates=0, verified_replays=5120,
                            provenance={'plan': {'path': str(args.plan), 'sha256': sha(args.plan)},
                                        'acceptance_result': {'path': str(args.acceptance_result), 'sha256': sha(args.acceptance_result)},
                                        'analyzer': {'path': str(Path(__file__).relative_to(Path.cwd())), 'sha256': sha(__file__)},
                                        'replay_metrics_binary': {'path': str(args.metrics_program), 'sha256': sha(args.metrics_program)},
                                        'source_ledger': {'path': str(args.work_dir / 'source-ledger.json'), 'sha256': sha(args.work_dir / 'source-ledger.json')},
                                        'rust_batches': receipts},
                            definitions={'win_rate_percent': '100 * wins / games', 'score_rate': '(wins + .5 * ties) / games',
                                         'mean_turns': 'legacy Rust metric: mean ceil(all action plies / 2); includes choose_noble',
                                         'vp_per_turn': 'sum player VP / sum player decisions, including choose_noble',
                                         'vp_per_main_action': 'sum player VP / sum player actions excluding choose_noble',
                                         'action_percentages': 'count / all decisions of that model, including choose_noble',
                                         'process_wall_seconds_sum': 'sum individual process elapsed times; parallel overlap, not campaign wall',
                                         'orientation': 'candidate identity and seat split before aggregation; never pooled physical P0=Pcandidate'},
                            pairs=pairs))
    print(f'PASS: {len(pairs)} pairs / 5120 replays; output {args.output}', flush=True)


if __name__ == '__main__':
    main()
