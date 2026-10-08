"""M56 finite big-card continuation. One final candidate, no retries or pool writes.

Unchanged M55 helpers provide bounded process ownership and export checks.
New seed layout, offline metrics and acceptance policy are frozen separately.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_ppo_fixed_eval as fixed
from scripts import prism_match_details as details
from scripts import prism_rush_round as legacy

ART = ROOT / 'local-artifacts/prism/alpha-v0.1.1'
PILOT = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.config.json'
TRAIN = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.train.json'
CONTROL = ART / 'controller-contract.json'
RESULT = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.result.json'
ANCHORS = ('heuristic-v031', 'prism-v01', 'prism-v0.1.1')
MODELS = ('base', 'candidate')
DISPLAY = {'base': 'Prism Alpha v0.1.0', 'candidate': 'Prism Alpha v0.1.1 候选',
           'base-t1': 'Prism Alpha v0.1.0（T=1）',
           'heuristic-v031': 'Heuristic v0.3.1（greedy）',
           'prism-v01': '初代 Prism v0.1.0（greedy）',
           'prism-v0.1.1': 'Prism v0.1.1（T=1）'}
read, write, sha, require = fixed.read_json, fixed.atomic_json, fixed.sha256_file, fixed._require
now = legacy.now
interval = legacy.interval
assert_grid = legacy.assert_grid
# Helpers run in this process only; their original source and M55 contract stay intact.
legacy.ART = ART


def frozen():
    control = read(CONTROL)
    for name, digest in control['files'].items():
        require(sha(ROOT / name) == digest, 'M56 frozen source/asset drift: ' + name)
    require(control['no_retry'] and control['only_final_c4'] and control['physical_games'] == 5504,
            'M56 finite scope')
    return control, read(PILOT), read(TRAIN)


def expected_grid(start, end, direct=False):
    return {(m, op, seed, seat) for m in (('candidate',) if direct else MODELS)
            for op in (('base-t1',) if direct else ANCHORS)
            for seed in range(start, end + 1) for seat in (0, 1)}


def measurements(rows, stats):
    start, end = stats['seed_start'], stats['seed_end']
    direct_end = stats['direct_seed_end']
    assert_grid(rows, expected_grid(start, end) | expected_grid(start, direct_end, True))
    keyed = {(r['candidate'], r['opponent'], r['seed'], r['candidate_seat']): r for r in rows}
    def delta(seed, key, opponents=ANCHORS):
        return math.fsum(float(keyed[('candidate', op, seed, seat)][key]) -
                         float(keyed[('base', op, seed, seat)][key])
                         for op in opponents for seat in (0, 1)) / (2 * len(opponents))
    seeds = range(start, end + 1)
    out = {'strength_pool': interval([delta(s, 'candidate_score') for s in seeds], stats),
           'bigcard_auc24': interval([delta(s, 'large_card_vp_auc24') for s in seeds], stats),
           'direct_parent': interval([math.fsum(keyed[('candidate', 'base-t1', s, seat)]['candidate_score']
                for seat in (0, 1)) / 2 for s in range(start, direct_end + 1)], stats)}
    # These describe opponent tradeoffs and the reward proxy; they do not add vetoes.
    for op in ANCHORS:
        out['diagnostic/strength/' + op] = interval([delta(s, 'candidate_score', (op,)) for s in seeds], stats)
    out['diagnostic/total_vp_auc24'] = interval([delta(s, 'rush_auc') for s in seeds], stats)
    out['diagnostic/vp8_by_main20'] = interval([delta(s, 'vp_threshold_by_horizon') for s in seeds], stats)
    gates = {'strength_pool': out['strength_pool']['simultaneous_one_sided_lower'] >= stats['strength_pool_delta_lower_gte'],
             'direct_parent': out['direct_parent']['simultaneous_one_sided_lower'] >= stats['direct_parent_score_lower_gte'],
             'bigcard_auc24': out['bigcard_auc24']['simultaneous_one_sided_lower'] >= stats['bigcard_auc24_delta_lower_gte']}
    require(len(gates) == stats['one_sided_claims'] == 3, 'M56 three-claim family')
    return out, gates


def descriptor(program, weights=None, args=None, action_seed=56020001):
    return {'program': str(Path(program).resolve()), 'sha256': sha(program),
            'args': args or ['agent-prism-sample', '--weights', str(Path(weights).resolve()), '--seed', str(action_seed)],
            'files': ([{'path': str(Path(weights).resolve()), 'sha256': sha(weights)}] if weights else [])}


def make_plan(stage, pilot, train):
    final = ART / 'campaign/cycle-4-export/weights.json'
    base = ROOT / pilot['base_model']['weights_path']
    engine = ROOT / 'local-artifacts/prism/acceptance-v1/build/release/splendor.exe'
    candidates = {'base': descriptor(engine, base), 'candidate': descriptor(engine, final)}
    opponents = {'prism-v0.1.1': descriptor(engine, ROOT / 'local-artifacts/prism/v0.1.1/weights.json')}
    for name in ANCHORS[:2]:
        desc = train['opponents'][name]; argv = list(desc['args'])
        if '--weights' in argv:
            i = argv.index('--weights') + 1; argv[i] = str((ROOT / argv[i]).resolve())
        opponents[name] = descriptor(ROOT / desc['program'], args=argv)
        opponents[name]['files'] = [{'path': str((ROOT / p).resolve()), 'sha256': digest} for p, digest in desc['files'].items()]
    cfg = {'format': fixed.FORMAT, 'engine': {'program': str(engine), 'sha256': sha(engine)},
           'catalog_fingerprint': train['run']['catalog_fingerprint'], 'action_seed': pilot[stage]['action_seed'],
           'candidates': candidates, 'opponents': opponents,
           'timeouts': {'game_wall_seconds': 60, 'handshake_timeout_ms': 10000,
                        'move_timeout_ms': 10000, 'shutdown_grace_ms': 1000}}
    work = ART / stage; (work / 'configs').mkdir(parents=True, exist_ok=True)
    shards = []
    for mode in ('anchors', 'direct') if stage == 'acceptance' else ('anchors',):
        end = pilot[stage]['direct_seed_end'] if mode == 'direct' else pilot[stage]['seed_end']
        for i, first in enumerate(range(pilot[stage]['seed_start'], end + 1, 32)):
            sub = json.loads(json.dumps(cfg)); sub['seeds'] = list(range(first, min(first + 32, end + 1)))
            if mode == 'direct':
                sub['candidates'] = {'candidate': candidates['candidate']}; sub['opponents'] = {'base-t1': candidates['base']}
            path = work / 'configs' / f'{mode}-{i}.json'; write(path, sub)
            validated = fixed.validate_config(sub, path); fixed.check_assets(validated)
            shards.append({'mode': mode, 'config': str(path), 'config_sha256': sha(path),
                           'output': str(work / 'runs' / f'{mode}-{i}'),
                           'games': len(sub['candidates']) * len(sub['opponents']) * len(sub['seeds']) * 2})
    require(sum(s['games'] for s in shards) == pilot[stage]['total_games'], 'stage physical budget')
    plan = {'format': 'm56-alpha-evaluation-plan-v1', 'stage': stage, 'started_after_final_c4': True,
            'created_at': now(), 'base_weights_sha256': sha(base), 'candidate_weights_sha256': sha(final), 'shards': shards}
    write(work / 'plan.json', plan)
    return plan


def profile_summary(profiles):
    n = len(profiles)
    result = {'games': n, 'mean_total_vp_auc24': math.fsum(p['rush_auc'] for p in profiles) / n,
              'mean_large_card_vp_auc24': math.fsum(p['large_card_vp_auc24'] for p in profiles) / n,
              'mean_terminal_large_card_printed_vp': math.fsum(p['terminal_large_card_printed_vp'] for p in profiles) / n,
              'mean_large_card_buys_within24': math.fsum(p['high_vp_buys_within_window'] for p in profiles) / n,
              'score_checkpoints': []}
    for key in ('first_large_card_main', 'first_4plus_card_main'):
        xs = [p[key] for p in profiles if p[key] is not None]
        result[key] = {'coverage_games': len(xs), 'coverage_rate': len(xs) / n,
                       'conditional_mean': math.fsum(xs) / len(xs) if xs else None}
    for i, main in enumerate((8, 12, 16, 20, 24)):
        cs = [p['score_checkpoints'][i] for p in profiles]
        result['score_checkpoints'].append({'own_main': main,
            'mean_vp': math.fsum(c['vp'] for c in cs) / n,
            'mean_large_card_printed_vp': math.fsum(c['large_card_printed_vp'] for c in cs) / n,
            'observed_games': sum(c['observed_before_terminal'] for c in cs), 'games': n})
    return result


def collect(plan, pilot, train):
    rows, ledger = [], []
    for shard in plan['shards']:
        cfg = read(shard['config']); require(sha(shard['config']) == shard['config_sha256'], 'config drift')
        validated = fixed.validate_config(cfg, shard['config']); fixed.check_assets(validated)
        out = Path(shard['output']); progress = read(out / 'progress.json')
        require(progress['config_sha256'] == fixed.canonical_hash(cfg) == fixed.canonical_hash(read(out/'config.json')), 'config/progress binding')
        completion = read(out/'completion.json')
        require(completion['result_sha256'] == sha(out/'result.json'), 'shard result drift')
        shard_rows = fixed._rows_from_progress(progress, validated)
        for row in shard_rows:
            path = out/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            game = read(path/'game.json'); rec = progress['games'][fixed._game_key(row['candidate'],row['opponent'],row['seed'],row['candidate_seat'])]
            require(game['status']=='completed' and game['row']==row, 'terminal record identity')
            hashes = {n:sha(path/n) for n in ('report.json','replay.json','process-result.json','match-config.json')}
            require(hashes['report.json']==game['report_sha256']==rec['report_sha256'] and hashes['replay.json']==game['replay_sha256']==rec['replay_sha256'], 'game artifact drift')
            match = read(path/'match-config.json')
            require(fixed.canonical_hash(match)==game['game_config_sha256'], 'match-config drift')
            replay, report, process = (read(path/n) for n in ('replay.json','report.json','process-result.json'))
            require(process['returncode']==0 and process['wall_seconds']>0,'process completion/timing')
            rebuilt = fixed._report_result(report,replay,game_id=match['game_id'],seed=row['seed'],seat=row['candidate_seat'],catalog=train['run']['catalog_fingerprint'])
            require(all(row[k]==v for k,v in rebuilt.items()),'report/progress mismatch')
            for seat in (0,1):
                descriptor = validated['candidates'][row['candidate']] if seat==row['candidate_seat'] else validated['opponents'][row['opponent']]
                require(match['agents'][seat]=={'program':descriptor['program_resolved'],'args':descriptor['args_resolved']},'player command/seat drift')
                hello = report['agents'][seat]
                expected = {'agent_name':'prism-sample','agent_version':'0.1.0'} if seat==row['candidate_seat'] or row['opponent'] in ('base-t1', 'prism-v0.1.1') else train['opponents'][row['opponent']]['hello']
                require(hello['seat']==seat and all(hello[k]==v for k,v in expected.items()), 'model/runtime handshake mismatch')
            row['_candidate_actions'],row['_opponent_actions']=Counter(),Counter()
            for step in replay['steps']:
                row['_candidate_actions' if step['actor']==row['candidate_seat'] else '_opponent_actions'][step['action']['type']]+=1
            row['_wall_seconds']=process['wall_seconds'];row['_replay_path']=str((path/'replay.json').resolve())
            rows.append(row); ledger.append({'path':str(path),'hashes':hashes})
    contract=pilot[plan['stage']]
    expected=expected_grid(contract['seed_start'],contract['seed_end'])
    if plan['stage']=='acceptance':expected|=expected_grid(contract['seed_start'],contract['direct_seed_end'],True)
    assert_grid(rows,expected)
    work=ART/plan['stage'];write(work/'source-ledger.json',ledger)
    manifest={'rows':[{'candidate':r['candidate'],'opponent':r['opponent'],'seed':r['seed'],'candidate_seat':r['candidate_seat'],'replay_path':r['_replay_path']} for r in rows]}
    write(work/'style-manifest.json',manifest)
    subprocess.run([str(ART/'build/release/examples/prism_bigcard_metrics.exe'),str(work/'style-manifest.json'),str(ART/'style.json'),str(work/'style-metrics.json')],check=True,timeout=120)
    styles=read(work/'style-metrics.json')['games']
    require(len(styles)==len(rows),'style coverage')
    for row, style in zip(rows,styles):
        require(all(row[k]==style[k] for k in ('candidate','opponent','seed','candidate_seat')),'style orientation')
        row.update(style['profiles'][row['candidate_seat']]); row['_profiles'] = style['profiles']
    groups=defaultdict(list)
    for row in rows:groups[(row['candidate'],row['opponent'],row['candidate_seat'])].append(row)
    metrics={}
    for key, items in sorted(groups.items()):
        name='-'.join(map(str,key));m=work/(name+'.manifest.json');out=work/(name+'.metrics.json')
        write(m,{'rows':[{'replay_path':r['_replay_path']} for r in items]})
        subprocess.run([str(ROOT/'local-artifacts/prism/v01/bin/s4_batch_metrics.exe'),str(m),str(out)],check=True,timeout=120,capture_output=True)
        metrics[key]=read(out)
    pairs=[]
    for model,op in sorted({(m,o) for m,o,_ in groups}):
        merged=groups[(model,op,0)]+groups[(model,op,1)]
        cb,ob,seats=[],[],[]
        for seat in (0,1):
            xs=groups[(model,op,seat)];m=metrics[(model,op,seat)]
            cm,om=m['seat_p0_first' if seat==0 else 'seat_p1_second'],m['seat_p1_second' if seat==0 else 'seat_p0_first']
            cb.append((cm,len(xs)));ob.append((om,len(xs)))
            seats.append({'candidate_seat':seat,'candidate':details.merge_player([(cm,len(xs))],xs,True),'opponent':details.merge_player([(om,len(xs))],xs,False),'macro':details.macro(xs)})
        pairs.append({'candidate':model,'opponent':op,'candidate_display':DISPLAY[model],'opponent_display':DISPLAY[op],
                      'candidate_metrics':details.merge_player(cb,merged,True),'opponent_metrics':details.merge_player(ob,merged,False),
                      'macro':details.macro(merged),'seats':seats,'score_uncertainty':details.score_ci(merged),
                      'candidate_bigcard':profile_summary([r['_profiles'][r['candidate_seat']] for r in merged]),
                      'opponent_bigcard':profile_summary([r['_profiles'][1-r['candidate_seat']] for r in merged]),
                      'mean_rush_auc':math.fsum(x['rush_auc'] for x in merged)/len(merged),
                      'vp8_by_main20_rate':sum(x['vp_threshold_by_horizon'] for x in merged)/len(merged),
                      'short_game_fraction':sum(x['shorter_than_reward_window'] for x in merged)/len(merged)})
    write(work/'match-details.json',{'format':'prism-model-match-details-v1','stage':plan['stage'],'status':'VERIFIED_OFFLINE_REPLAY_METRICS','verified_replays':len(rows),'pairs':pairs,
          'plan_sha256':sha(work/'plan.json'),'source_ledger_sha256':sha(work/'source-ledger.json'),'style_metrics_sha256':sha(work/'style-metrics.json')})
    return rows,pairs




def watch():
    control, pilot, train = frozen()
    require(not (ART / 'controller-completion.json').exists(), 'controller already finalized')
    lock = ART / 'controller.lock'; fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    try:
        write(ART / 'controller-status.json', {'state': 'WAITING_FOR_C4', 'timestamp': now(), 'planned_games': 5504})
        training = legacy.wait_training(control); frozen()
        result = {'format': 'm56-prism-alpha-result-v1', 'baseline_git_commit': pilot['baseline_git_commit'],
                  'config_sha256': sha(PILOT), 'train_sha256': sha(TRAIN), 'controller_sha256': sha(__file__),
                  'model_version': 'prism-alpha-v0.1.1', 'display_name': 'Prism Alpha v0.1.1',
                  'base_model': pilot['base_model'], 'training': training,
                  'default_replaced': False, 'shared_pool_deployed': False, 'git_published': False,
                  'retries': 0, 'candidate_selection': 'fixed final c4 only',
                  'style_reward': pilot['style'], 'acceptance_policy': pilot['acceptance']}
        for stage in ('development', 'acceptance'):
            write(ART / 'controller-status.json', {'state': stage.upper() + '_RUNNING', 'timestamp': now()})
            plan = make_plan(stage, pilot, train); frozen(); legacy.run_plan(plan, control); frozen()
            rows, pairs = collect(plan, pilot, train)
            result[stage] = {'games': len(rows), 'pairs': pairs, 'run_receipt': read(ART / stage / 'run-receipt.json'),
                             'match_details_path': str(ART / stage / 'match-details.json'),
                             'match_details_sha256': sha(ART / stage / 'match-details.json')}
            if stage == 'acceptance':
                result['measurements'], result['gates'] = measurements(rows, pilot['acceptance'])
        result['all_three_gates_passed'] = all(result['gates'].values())
        result['status'] = 'ACCEPTED_BIGCARD_CONTINUATION' if result['all_three_gates_passed'] else 'NOT_ACCEPTED_BIGCARD_CONTINUATION'
        result['confirmed_enhancement'] = {
            'strength_pool': result['measurements']['strength_pool']['simultaneous_one_sided_lower'] > 0,
            'direct_parent': result['measurements']['direct_parent']['simultaneous_one_sided_lower'] > .5,
            'bigcard_auc24': result['measurements']['bigcard_auc24']['simultaneous_one_sided_lower'] > 0}
        result['physical_games'] = 5504; result['completed_at'] = now()
        write(RESULT, result)
        from scripts.prism_alpha_report import finalize_documents
        finalize_documents(result); frozen()
        for command in (['git', 'diff', '--check'], ['git', 'check-ignore', 'handoff.md'],
                        ['git', 'check-ignore', 'local-artifacts/prism/alpha-v0.1.1']):
            checked = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            require(checked.returncode == 0, 'closeout publication check: ' + str(command))
        write(ART / 'closeout-validation.json', {'status': 'PASS', 'total_physical_games': 5504,
            'all_evaluation_replays_rule_verified': 4480, 'formal_gates_analyzed_once': True,
            'source_and_base_hashes_unchanged': True, 'result_sha256': sha(RESULT),
            'report_sha256': sha(ROOT / 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md'),
            'no_retry_no_extra_training_no_pool_mutation': True, 'completed_at': now()})
        write(ART / 'controller-completion.json', {'status': result['status'], 'result_path': str(RESULT),
                                                'result_sha256': sha(RESULT), 'completed_at': now()})
        write(ART / 'controller-status.json', {'state': 'COMPLETE', 'verdict': result['status'], 'timestamp': now()})
    except BaseException as exc:
        write(ART / 'controller-status.json', {'state': 'FAILED', 'timestamp': now(),
              'type': type(exc).__name__, 'error': str(exc), 'retry': False})
        raise
    finally:
        lock.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    if args.watch: watch()
    else: parser.error('explicit --watch required; importing never dispatches games')
