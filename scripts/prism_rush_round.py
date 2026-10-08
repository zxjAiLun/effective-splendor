"""One bounded M55 rush round. Owns only fixed local evaluation jobs and reports.

Training is separately supervised; this controller waits for its final c4 and
never retries a match, tunes parameters, changes a pool or publishes Git.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts import prism_ppo_fixed_eval as fixed
from scripts import prism_match_details as details

PILOT = ROOT / 'benchmarks/m55-prism-rush-v0.1.0.config.json'
TRAIN = ROOT / 'benchmarks/m55-prism-rush-v0.1.0.train.json'
ART = ROOT / 'local-artifacts/prism/rush-v0.1.0'
CONTROL = ART / 'controller-contract.json'
RESULT = ROOT / 'benchmarks/m55-prism-rush-v0.1.0.result.json'
ANCHORS = ('heuristic-v031', 'prism-v01')
MODELS = ('base', 'rush')
DISPLAY = {'base': 'Prism v0.1.1', 'rush': 'Prism Rush v0.1.0 候选',
           'base-t1': 'Prism v0.1.1（T=1）', 'heuristic-v031': 'Heuristic v0.3.1（greedy）',
           'prism-v01': '初代 Prism v0.1.0（greedy）'}
read, write, sha = fixed.read_json, fixed.atomic_json, fixed.sha256_file
require = fixed._require


def now():
    return datetime.now(timezone.utc).isoformat()


def frozen():
    c = read(CONTROL)
    for name, digest in c['files'].items():
        require(sha(ROOT / name) == digest, f'frozen source/asset drift: {name}')
    require(c['no_retry'] is True and c['workers'] == 4 and c['only_final_c4'] is True,
            'finite controller scope')
    return c, read(PILOT), read(TRAIN)


def expected_grid(start, end, direct=False):
    return {(m, op, seed, seat) for m in (('rush',) if direct else MODELS)
            for op in (('base-t1',) if direct else ANCHORS)
            for seed in range(start, end + 1) for seat in (0, 1)}


def assert_grid(rows, expected):
    keys = [(r['candidate'], r['opponent'], r['seed'], r['candidate_seat']) for r in rows]
    require(len(keys) == len(set(keys)) and set(keys) == expected, 'incomplete/duplicate/unexpected evaluation grid')


def interval(values, stats):
    xs = np.asarray(values, dtype=float)
    require(xs.ndim == 1 and len(xs) > 0 and np.isfinite(xs).all(), 'invalid paired measurements')
    rng = np.random.default_rng(stats['bootstrap_rng_seed'])
    samples = np.concatenate([xs[rng.integers(0, len(xs), (min(1000, stats['bootstrap_samples']-i), len(xs)))].mean(1)
                              for i in range(0, stats['bootstrap_samples'], 1000)])
    return {'mean': float(xs.mean()), 'ci95': np.quantile(samples, [.025, .975]).tolist(),
            'simultaneous_one_sided_lower': float(np.quantile(samples, stats['lower_quantile'])),
            'seed_blocks': len(xs)}


def measurements(rows, stats):
    start, end = stats['seed_start'], stats['seed_end']
    assert_grid(rows, expected_grid(start, end) | expected_grid(start, end, True))
    keyed = {(r['candidate'], r['opponent'], r['seed'], r['candidate_seat']): r for r in rows}
    def delta(seed, key, opponents=ANCHORS):
        return math.fsum(float(keyed[('rush', op, seed, seat)][key]) - float(keyed[('base', op, seed, seat)][key])
                         for op in opponents for seat in (0, 1)) / (2 * len(opponents))
    seeds = range(start, end+1)
    out = {'strength_pool': interval([delta(s, 'candidate_score') for s in seeds], stats)}
    for op in ANCHORS:
        out['strength/' + op] = interval([delta(s, 'candidate_score', (op,)) for s in seeds], stats)
    out['direct_base'] = interval([math.fsum(keyed[('rush', 'base-t1', s, seat)]['candidate_score'] for seat in (0, 1))/2 for s in seeds], stats)
    out['rush_auc'] = interval([delta(s, 'rush_auc') for s in seeds], stats)
    out['vp8_by_main20'] = interval([delta(s, 'vp_threshold_by_horizon') for s in seeds], stats)
    gates = {'strength_pool': out['strength_pool']['simultaneous_one_sided_lower'] >= stats['strength_pool_delta_lower_gte'],
             'direct_base': out['direct_base']['simultaneous_one_sided_lower'] >= stats['direct_base_score_lower_gte'],
             'rush_auc': out['rush_auc']['simultaneous_one_sided_lower'] > stats['rush_auc_delta_lower_gt'],
             'vp8_by_main20': out['vp8_by_main20']['simultaneous_one_sided_lower'] > stats['vp8_by_main20_rate_delta_lower_gt']}
    for op in ANCHORS:
        gates['strength/' + op] = out['strength/' + op]['simultaneous_one_sided_lower'] >= stats['strength_each_anchor_delta_lower_gte']
    require(len(gates) == stats['one_sided_claims'] == 6, 'claim family')
    return out, gates


def pinned_descriptor(program, weights=None, args=None):
    return {'program': str(Path(program).resolve()), 'sha256': sha(program),
            'args': args or ['agent-prism-sample', '--weights', str(Path(weights).resolve()), '--seed', '55020001'],
            'files': ([{'path': str(Path(weights).resolve()), 'sha256': sha(weights)}] if weights else [])}


def make_plan(stage, pilot, train):
    final = ART / 'campaign/cycle-4-export/weights.json'
    require(final.is_file(), 'final c4 export missing')
    base = ROOT / pilot['base_model']['weights_path']
    engine = ROOT / 'local-artifacts/prism/acceptance-v1/build/release/splendor.exe'
    candidates = {'base': pinned_descriptor(engine, base), 'rush': pinned_descriptor(engine, final)}
    opponents = {}
    for name in ANCHORS:
        desc = train['opponents'][name]
        argv = list(desc['args'])
        files = [{'path': str((ROOT / p).resolve()), 'sha256': digest} for p, digest in desc['files'].items()]
        if '--weights' in argv:
            i = argv.index('--weights')+1; argv[i] = str((ROOT / argv[i]).resolve())
        opponents[name] = {'program': str((ROOT / desc['program']).resolve()), 'sha256': desc['sha256'], 'args': argv, 'files': files}
    cfg = {'format': fixed.FORMAT, 'engine': {'program': str(engine), 'sha256': sha(engine)},
           'catalog_fingerprint': train['run']['catalog_fingerprint'], 'action_seed': pilot[stage]['action_seed'],
           'candidates': candidates, 'opponents': opponents,
           'timeouts': {'game_wall_seconds': 60, 'handshake_timeout_ms': 10000, 'move_timeout_ms': 10000, 'shutdown_grace_ms': 1000}}
    work = ART / stage; (work / 'configs').mkdir(parents=True, exist_ok=True)
    shards = []
    for mode in ('anchors', 'direct') if stage == 'acceptance' else ('anchors',):
        for i, first in enumerate(range(pilot[stage]['seed_start'], pilot[stage]['seed_end']+1, 32)):
            sub = json.loads(json.dumps(cfg)); sub['seeds'] = list(range(first, min(first+32, pilot[stage]['seed_end']+1)))
            if mode == 'direct':
                sub['candidates'] = {'rush': candidates['rush']}; sub['opponents'] = {'base-t1': candidates['base']}
            path = work / 'configs' / f'{mode}-{i}.json'; write(path, sub)
            validated = fixed.validate_config(sub, path); fixed.check_assets(validated)
            shards.append({'mode': mode, 'config': str(path), 'config_sha256': sha(path),
                           'output': str(work / 'runs' / f'{mode}-{i}'),
                           'games': len(sub['candidates'])*len(sub['opponents'])*len(sub['seeds'])*2})
    require(sum(s['games'] for s in shards) == pilot[stage]['total_games'], 'stage physical budget')
    plan = {'format': 'm55-rush-evaluation-plan-v1', 'stage': stage, 'started_after_final_c4': True,
            'created_at': now(), 'base_weights_sha256': sha(base), 'rush_weights_sha256': sha(final), 'shards': shards}
    write(work / 'plan.json', plan)
    return plan


def run_plan(plan, control):
    from training.prism.ppo.processes import ProcessTree
    stop = time.monotonic() + control['evaluation_wall_seconds']
    abort = threading.Event()
    def worker(shard):
        require(not abort.is_set() and time.monotonic() < stop, 'stage stopped before dispatch')
        require(sha(shard['config']) == shard['config_sha256'], 'shard drift')
        out = Path(shard['output']); require(not out.exists(), 'no retry or duplicate stage launch')
        label = out.name
        logs = out.parent.parent / 'logs'; logs.mkdir(exist_ok=True)
        argv = [sys.executable, '-B', str(ROOT / 'scripts/prism_ppo_fixed_eval.py'), '--config', shard['config'], '--output', shard['output']]
        with (logs / (label+'.stdout.log')).open('wb') as stdout, (logs / (label+'.stderr.log')).open('wb') as stderr:
            with ProcessTree(cpu_seconds=control['worker_cpu_seconds'], memory_bytes=control['worker_memory_bytes'], max_processes=4) as tree:
                process = tree.start(argv, cwd=str(ROOT), stdout=stdout, stderr=stderr)
                # Child priority inherits this BelowNormal controller.
                receipt = tree.wait(wall_seconds=max(1, stop-time.monotonic()), storage_root=ART,
                                    max_storage_bytes=control['max_storage_bytes'])
        write(logs / (label+'.receipt.json'), dict(receipt, argv=argv, config_sha256=shard['config_sha256']))
        if receipt['returncode'] != 0 or receipt['stop_reason'] is not None:
            abort.set()
            raise ValueError('evaluation failed; retained, no retry')
        return label
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=control['workers']) as pool:
        futures=[pool.submit(worker, shard) for shard in plan['shards']]
        try:
            for future in as_completed(futures):
                label=future.result()
                print(json.dumps({'event': 'evaluation_shard_complete', 'stage': plan['stage'], 'shard': label}), flush=True)
        except BaseException:
            abort.set()
            for future in futures:future.cancel()
            raise
    write(ART / plan['stage'] / 'run-receipt.json', {'status': 'PASS', 'wall_seconds': time.monotonic()-started,
          'workers': control['workers'], 'priority': 'BelowNormal', 'physical_games': sum(s['games'] for s in plan['shards']), 'retries': 0})


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
                expected = {'agent_name':'prism-sample','agent_version':'0.1.0'} if seat==row['candidate_seat'] or row['opponent']=='base-t1' else train['opponents'][row['opponent']]['hello']
                require(hello['seat']==seat and all(hello[k]==v for k,v in expected.items()), 'model/runtime handshake mismatch')
            row['_candidate_actions'],row['_opponent_actions']=Counter(),Counter()
            for step in replay['steps']:
                row['_candidate_actions' if step['actor']==row['candidate_seat'] else '_opponent_actions'][step['action']['type']]+=1
            row['_wall_seconds']=process['wall_seconds'];row['_replay_path']=str((path/'replay.json').resolve())
            rows.append(row); ledger.append({'path':str(path),'hashes':hashes})
    contract=pilot[plan['stage']]
    expected=expected_grid(contract['seed_start'],contract['seed_end'])
    if plan['stage']=='acceptance':expected|=expected_grid(contract['seed_start'],contract['seed_end'],True)
    assert_grid(rows,expected)
    work=ART/plan['stage'];write(work/'source-ledger.json',ledger)
    manifest={'rows':[{'candidate':r['candidate'],'opponent':r['opponent'],'seed':r['seed'],'candidate_seat':r['candidate_seat'],'replay_path':r['_replay_path']} for r in rows]}
    write(work/'style-manifest.json',manifest)
    subprocess.run([str(ART/'build/release/examples/prism_rush_metrics.exe'),str(work/'style-manifest.json'),str(ART/'style.json'),str(work/'style-metrics.json')],check=True,timeout=120)
    styles=read(work/'style-metrics.json')['games']
    require(len(styles)==len(rows),'style coverage')
    for row, style in zip(rows,styles):
        require(all(row[k]==style[k] for k in ('candidate','opponent','seed','candidate_seat')),'style orientation')
        row.update(style['profiles'][row['candidate_seat']])
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
                      'mean_rush_auc':math.fsum(x['rush_auc'] for x in merged)/len(merged),
                      'vp8_by_main20_rate':sum(x['vp_threshold_by_horizon'] for x in merged)/len(merged),
                      'short_game_fraction':sum(x['shorter_than_reward_window'] for x in merged)/len(merged)})
    write(work/'match-details.json',{'format':'prism-model-match-details-v1','stage':plan['stage'],'status':'VERIFIED_OFFLINE_REPLAY_METRICS','verified_replays':len(rows),'pairs':pairs,
          'plan_sha256':sha(work/'plan.json'),'source_ledger_sha256':sha(work/'source-ledger.json'),'style_metrics_sha256':sha(work/'style-metrics.json')})
    return rows,pairs


def verify_final_export(run):
    import torch
    from training.prism.export import load_weights
    from training.prism.data import collate_states
    final=ART/'campaign/cycle-4-export/weights.json'
    manifest=read(final.with_name('weights.manifest.json'))
    require(manifest['weights_sha256']==sha(final) and len(manifest['tensors'])==32,'export identity/schema')
    exported=load_weights(final,expected_catalog_fingerprint=run.config['catalog_fingerprint'])
    require(all(torch.equal(v,exported.state_dict()[k]) for k,v in run.learner.model.policy.state_dict().items()),'export/c4 policy tensor mismatch')
    fixtures=ROOT/'local-artifacts/prism/v01/provenance/boundary-fixtures.jsonl'
    states=[json.loads(line).get('input',json.loads(line)) for line in fixtures.read_text(encoding='utf-8').splitlines()]
    work=ART/'c4-parity';work.mkdir()
    inputs=work/'inputs.jsonl';inputs.write_text(''.join(json.dumps(state)+'\n' for state in states),encoding='utf-8')
    output=work/'rust.jsonl'
    program=ROOT/'local-artifacts/prism/acceptance-v1/build/release/splendor.exe'
    completed=subprocess.run([str(program),'prism-predict','--weights',str(final),'--input',str(inputs),'--output',str(output)],capture_output=True,text=True,timeout=90)
    require(completed.returncode==0,'c4 Rust export parity inference failed: '+completed.stderr)
    predictions=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
    require(len(predictions)==len(states)>0,'parity fixture coverage')
    worst=0.
    with torch.inference_mode():
        for state,pred in zip(states,predictions):
            logits,value,_=run.learner.model.forward_batch(collate_states([state]))
            rust=torch.tensor(pred['logits'],dtype=torch.float32)
            torch.testing.assert_close(logits[0],rust,atol=1e-4,rtol=1e-4)
            require(math.isclose(value.sigmoid().item(),pred['value'],abs_tol=1e-4,rel_tol=1e-4),'export value parity')
            worst=max(worst,(logits[0]-rust).abs().max().item())
    receipt={'status':'PASS','boundary_states':len(states),'max_abs_logit_error':worst,'atol':1e-4,'rtol':1e-4,
             'final_weights_sha256':sha(final),'new_games':0,'inference_overlay':False,'exported_tensors':32}
    write(work/'receipt.json',receipt)
    return receipt


def wait_training(control):
    launch=json.loads((ART/'launch.json').read_text(encoding='utf-8-sig'))
    deadline=time.monotonic()+control['training_wait_seconds']
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];api.OpenProcess.restype=ctypes.c_void_p
    api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.OpenProcess(0x1000,0,launch['pid'])
    try:
        while True:
            sessions=read(ART/'campaign/supervisor-sessions.json')
            if sessions and sessions[-1]['status']=='FINISHED':
                require(sessions[-1]['returncode']==0 and sessions[-1]['stop_reason'] is None,'training supervisor failed; no new evaluation')
                break
            if handle:
                code=ctypes.c_uint32();require(api.GetExitCodeProcess(handle,ctypes.byref(code)) and code.value==259,'training process ended before clean receipt')
            require(time.monotonic()<deadline,'bounded training wait exhausted')
            time.sleep(10)
    finally:
        if handle:api.CloseHandle(handle)
    from training.prism.ppo.coordinator import Run
    run=Run.open(ART/'campaign/run')
    require(run.state['phase']=='COMMITTED' and run.state['cycle']==4 and not run.state['paused'],'final training commit')
    require(run.state['attempts']==1024 and len(run.state['all_jobs'])==1024,'training physical budget/coverage')
    require(len(run.state['consumed'])==4,'exactly four batches consumed')
    export_parity=verify_final_export(run)
    styles=[m for m in run.state['metrics'] if m.get('event')=='style_extracted']
    require(len(styles)==4,'style extractor ran each cycle')
    receipt={'status':'PASS','run_identity':run.identity,'source_identity':control['training_source_identity'],
             'export_parity':export_parity,'games':1024,'decisions':run.state['decisions'],'new_steps':run.state['global_step'],
             'updates':run.state['update_attempts'],'fresh_optimizer':True,'style_cycles':styles,'supervisor_sessions':sessions,
             'final_weights_sha256':sha(ART/'campaign/cycle-4-export/weights.json')}
    write(ART/'training-receipt.json',receipt)
    return receipt


def watch():
    control,pilot,train=frozen()
    require(not (ART/'controller-completion.json').exists(),'controller already finalized')
    lock=ART/'controller.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        write(ART/'controller-status.json',{'state':'WAITING_FOR_C4','timestamp':now(),'planned_games':4096})
        training=wait_training(control);frozen()
        result={'format':'m55-prism-rush-result-v1','baseline_git_commit':pilot['baseline_git_commit'],
                'pilot_sha256':sha(PILOT),'train_sha256':sha(TRAIN),'controller_sha256':sha(__file__),
                'model_version':'prism-rush-v0.1.0','base_model':pilot['base_model'],'training':training,
                'default_replaced':False,'shared_pool_deployed':False,'git_published':False,'retries':0,'candidate_selection':'fixed final c4 only'}
        for stage in ('development','acceptance'):
            write(ART/'controller-status.json',{'state':stage.upper()+'_RUNNING','timestamp':now()})
            plan=make_plan(stage,pilot,train);frozen();run_plan(plan,control);frozen()
            rows,pairs=collect(plan,pilot,train)
            result[stage]={'games':len(rows),'pairs':pairs,'run_receipt':read(ART/stage/'run-receipt.json'),
                           'match_details_path':str(ART/stage/'match-details.json'),'match_details_sha256':sha(ART/stage/'match-details.json')}
            if stage=='acceptance':
                result['measurements'],result['gates']=measurements(rows,pilot['acceptance'])
        result['status']='ACCEPTED_RUSH_STYLE_ITERATION' if all(result['gates'].values()) else 'NOT_ACCEPTED_RUSH_STYLE'
        result['all_six_gates_passed']=all(result['gates'].values());result['physical_games']=4096;result['completed_at']=now()
        write(RESULT,result)
        from scripts.prism_rush_report import finalize_documents
        finalize_documents(result)
        frozen()
        require(sha(ROOT/pilot['base_model']['weights_path'])==pilot['base_model']['sha256'],'frozen base changed')
        for command in (["git","diff","--check"],["git","check-ignore","handoff.md"],["git","check-ignore","local-artifacts/prism/rush-v0.1.0"]):
            checked=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            require(checked.returncode==0,'documentation/publication check failed: '+str(command))
        receipt={'status':'PASS','total_physical_games':4096,'all_replays_rule_verified':3072,
                 'formal_gates_analyzed_once':True,'source_and_base_hashes_unchanged':True,
                 'result_sha256':sha(RESULT),'report_sha256':sha(ROOT/'docs/prism/prism-rush-v0.1.0-evaluation-summary.md'),
                 'no_retry_no_extra_training_no_pool_mutation':True,'completed_at':now()}
        write(ART/'closeout-validation.json',receipt)
        write(ART/'controller-completion.json',{'status':result['status'],'result_path':str(RESULT),'result_sha256':sha(RESULT),'completed_at':now()})
        write(ART/'controller-status.json',{'state':'COMPLETE','verdict':result['status'],'timestamp':now()})
    except BaseException as exc:
        write(ART/'controller-status.json',{'state':'FAILED','timestamp':now(),'type':type(exc).__name__,'error':str(exc),'retry':False})
        raise
    finally:
        lock.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    if args.watch:watch()
    else:parser.error('explicit --watch required; importing never dispatches games')
