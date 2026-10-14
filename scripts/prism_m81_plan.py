"""Generate and validate the M81 design bundle. This tool cannot run research."""
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / 'benchmarks/m81-anchor-coverage.execution-plan.json'
COMMON = ['heuristic', 'general', 'balance', 'alpha', 'beta', 'released-alpha']
COVERAGE = ['latest-alpha', 'latest-balance']
A_ORDER = ['general', 'parent', 'latest-alpha', 'latest-balance'] * 4
B_ORDER = A_ORDER.copy()
for i, opponent in [(3, 'heuristic'), (6, 'balance'), (9, 'heuristic'), (12, 'balance')]:
    B_ORDER[i] = opponent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def design():
    old_path = ROOT / 'benchmarks/m79-prism-mainline.execution-plan.json'
    old = json.loads(old_path.read_text(encoding='utf-8'))
    assets = {k: copy.deepcopy(old['assets'][k]) for k in sorted(set(COMMON + COVERAGE + ['parent'])) if k != 'heuristic'}
    assets['heuristic'] = {'label': 'Heuristic v0.3.1', 'command': ['agent-heuristic-v02', '--seed', '81090002'],
                           'identity_policy': 'Bind exact engine SHA and heuristic descriptor from M79 frozen evaluation, plus golden player-observation action parity before launch. A newer same-named heuristic is not interchangeable.'}
    assets['heuristic']['engine_sha256'] = '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'
    assets['heuristic']['verified_source_path'] = '/mnt/workspace/splendor-m79-mainline-r4/bin/splendor'
    ranges = {o: [81010000 + i * 1000, 81010255 + i * 1000] for i, o in enumerate(COMMON + COVERAGE)}
    plan = {
        'format': 'prism-m81-anchor-coverage-pilot-plan-v1', 'round': 'M81', 'status': 'DESIGNED_EXECUTOR_READY',
        'task_kind_now': 'existing-replay-diagnosis-and-design', 'new_games_by_planner': 0,
        'authorization': 'User requested existing-replay diagnosis and a plan directly executable by Sol. This turn delivers the design. When user forwards the accompanying execute instruction, Sol proceeds through finite R0-R9 without another start confirmation.',
        'question': 'Does replacing 25% of the M79 training mixture with two neglected opponents recover anchor performance without sacrificing broad strength?',
        'hypothesis': 'A distribution shift in early/middle resource planning is repairable by opponent coverage. Reserve penalty is not justified by existing replay evidence.',
        'scope': 'One paired training seed, two arms: a finite method-screening pilot. No robust multi-seed algorithm claim. Same budget A/B makes the mixture intervention testable within this seed.',
        'inputs': {'m79_plan': {'path': str(old_path.relative_to(ROOT)).replace('\\','/'), 'sha256': sha(old_path)},
                   'm79_numeric_blueprint': {'path': 'benchmarks/m79-prism-mainline.a-train.json', 'sha256': sha(ROOT/'benchmarks/m79-prism-mainline.a-train.json')},
                   'diagnostic': {'path': 'local-artifacts/prism/m79-mainline/regression-diagnostic/diagnostic.json', 'sha256': sha(ROOT/'local-artifacts/prism/m79-mainline/regression-diagnostic/diagnostic.json')},
                   'diagnostic_summary': {'path': 'local-artifacts/prism/m79-mainline/regression-diagnostic/summary.json', 'sha256': sha(ROOT/'local-artifacts/prism/m79-mainline/regression-diagnostic/summary.json')}},
        'assets': assets,
        'training': {
            'parent': 'parent', 'parent_label': 'M75 c20', 'initialization': 'fresh AdamW optimizer and fresh RNG, exact same parent weights for both arms; not M79 full-state resume',
            'paired_training_seeds': 1, 'run_seed': 81090001, 'environment_seed_range': [81001000,81003559],
            'cycles': 20, 'seed_blocks_per_cycle': 128, 'seats': [0,1], 'games_per_arm': 5120, 'total_games': 10240,
            'arms': {'A': {'role': 'same-budget control', 'opponent_period': A_ORDER}, 'B': {'role': 'fixed treatment candidate', 'opponent_period': B_ORDER}},
            'schedule': 'seed=81001000+128*cycle_index+block; opponent=period[block%16]; dispatch each physical seat once. 75% of A/B slots have identical opponent+seed+seat; replacement slots retain seed/seat with declared changed opponent.',
            'ppo': old['training']['ppo'], 'mode': 'categorical-T1', 'opponent_mode': 'greedy', 'ply_cap': 256,
            'exports': [5,10,15,20], 'final_candidate': 'B c20 fixed before all independent outcomes; A c20 always reported as control. No best-checkpoint, best-arm or best-seed selection.',
            'max_scientific_truncations_per_arm': 8, 'truncation_policy': 'retain prefix/cost, no refill; ninth scientific truncation ends that arm as failed. Other completed valid arms and report proceed.',
            'development_matches': 0, 'development_policy': 'No intermediate match sweep: candidate is fixed c20. Track numerical diagnostics and audit exports; all formal comparison uses the frozen new final grid.',
            'unchanged': ['architecture','encoder','outcome reward','value target','PPO hyperparameters','precision','CPU thread policy','sampling temperature','update ordering','minibatch/pass semantics'],
        },
        'evaluation': {
            'actors': ['base','A','B'], 'base': 'exact M75 c20', 'opponents': COMMON+COVERAGE,
            'common_opponents': COMMON, 'coverage_opponents': COVERAGE, 'mode': 'both-greedy',
            'seed_by_opponent': ranges, 'games_per_actor_per_opponent': 512, 'per_actor_common_and_coverage': 4096,
            'direct_parent': {'actors':['A','B'],'opponent':'parent','seed_range':[81030000,81030511],'games_per_actor':1024},
            'total_games': 14336, 'action_seed':81090002,'seats':[0,1],'shard_seed_blocks':32,'ply_cap':512,
            'old_m79_data_role': 'used for diagnosis/hypothesis only; never counted as independent M81 confirmation',
            'shared_baseline': 'Evaluate M75 once on new cohort; shared exact rows for both A/base and B/base comparisons.',
            'max_scientific_truncations':8, 'missing_policy':'No seed substitution or outcome imputation. Missing terminal/seat blocks the affected endpoint; report complete endpoints. Ninth scientific truncation stops new eval dispatch, preserving all evidence.',
            'held_out_opponents_for_B':['alpha','beta','released-alpha'],
            'coverage_note':'Heuristic and old Balance become training opponents in B. Their new-seed tests measure in-opponent retention, not unseen-opponent generalization.'},
        'statistics': {
            'metric':'half score=(W+0.5D)/N; pure win rate separate', 'unit':'first average both seats within each environment seed; same seed blocks resampled jointly across base/A/B',
            'bootstrap_samples':20000,'bootstrap_seed':81099999,'rng':'PCG64','quantile_method':'linear','ordinary_ci':[.025,.975],
            'endpoint_order':['B-A-targets','B-A-eight-pool','B-A-latest-alpha','B-A-latest-balance','B-base-common','B-parent','B-base-heuristic','B-base-balance','B-base-released-alpha','B-base-latest-alpha','B-base-latest-balance'],
            'pool_rule':'Target pair equal weight; original six-opponent pool equal weight; separate eight-opponent diagnostic pool equal weight. Independently resample each opponent seed block within a replicate.',
            'method_screen': {
                'primary':{'endpoint':'B-A-targets','targets':['heuristic','balance'],'point_min':.02,'lower_quantile':.05,'lower_strictly_greater_than':0},
                'retention_family':{'endpoints':['B-A-eight-pool','B-A-latest-alpha','B-A-latest-balance'],'one_sided_lower_quantile':.05/3,'lower_min':[-.02,-.03,-.03]},
                'pass_rule':'All four endpoints complete and pass. A single-seed pilot finding only; report each target separately even if mean passes.'},
            'mainline_candidate': {
                'fixed_candidate':'B c20',
                'enhancement_family':{'lower_quantile':.025,'common_delta_point_min':.02,'common_delta_lower_gt':0,'direct_parent_point_min':.52,'direct_parent_lower_gt':.50},
                'coverage_family':{'lower_quantile':.025,'latest_each_delta_lower_min':-.03},
                'anchor_family':{'lower_quantile':.05/3,'opponents':['heuristic','balance','released-alpha'],'each_delta_lower_min':-.03},
                'additional_retention':{'lower_quantile':.025,'common_delta_lower_min':-.05,'direct_parent_lower_min':.45},
                'pass_rule':'Every declared B gate complete and pass. Method-screen status is reported separately. Recommendation only, no release/default/deployment.'},
            'power':'Fixed practical screening grid, no claim of 80% power for +2pp or 3pp noninferiority. A wide CI means inconclusive; no automatic extra samples.',
            'training_seed_uncertainty':'one paired seed; game-level CI does not estimate recipe robustness across training seeds'},
        'style':{'role':'descriptive','comparison':'A and B versus M75 on exact shared six-opponent cohort; also A versus B',
                 'metrics':['early token choices and first divergence','reserve/buy counts and timing','opportunity-conditioned buying','0-5VP purchases','first big timing+coverage','Main12/24 score+coverage','early real discount redemption','nobles from actual ownership, not choose_noble action count','VP/Main'],
                 'fixed_style_reference_new_games':0,'route':'undetermined/mixed/provisional permitted; no confirmed style or new version identity'},
        'resources': {
            'deadline_mode':'resource_bounded_no_calendar_stop','absolute_stop':None,'round_elapsed_wall_stop':None,'eta_is_stop_condition':False,
            'total_cpu_seconds':480000,'training_cpu_seconds_per_arm':150000,'evaluation_cpu_seconds':150000,'audit_control_cpu_seconds':30000,
            'per_arm_storage_bytes':34359738368,'per_node_free_reserve_bytes':8589934592,
            'training_worker_slots_max':4,'training_torch_threads':2,'eval_worker_slots_max':8,'eval_threads_per_worker':1,
            'training_rss_bytes':8589934592,'eval_rss_bytes_per_worker':2147483648,
            'max_jobs_per_arm':5120,'max_decisions_per_arm':1310720,'max_update_attempts_per_arm':8192,
            'engineering_new_games':0,'research_logical_attempts':24576,'extra_infrastructure_attempts':128,'physical_attempt_ceiling':24704,
            'game_wall_seconds':90,'game_cpu_seconds':30,'move_timeout_ms':10000,'handshake_timeout_ms':10000,
            'wall_policy':'No date/time or elapsed-wall round kill. Preserve per-game hang detection and measured cumulative CPU/storage/attempt bounds. Old M79 absolute_stop, deadline fields and coordinator max_run_seconds must not silently survive in the new runtime.',
            'placement':'Prefer DSW=A, DSW2=B in isolated roots; after train+audit either node claims remaining evaluation shards through one commit/lease authority.',
            'single_node_fallback':'If only DSW reachable, run A then B automatically. Audit and archive completed A raw history with remote full-member SHA verification before reclaiming only M81-owned duplicate raw files as needed. Retain weights, full final optimizer/RNG state, manifests, reports, source and restore instructions. Never delete M79 history or wait for DSW2 as prerequisite.',
            'capacity':'Derive concurrency from actual cpuset+CPU quota+memory+free disk; combined reservations fit all active writers. Reuse M79 measured storage/CPU as estimates, verify actual growth every cycle.',
            'cost_estimate':'Historical M79 training used 54654 CPU seconds including retained history; two comparable arms roughly 109308 CPU seconds before new repairs/evaluation. Hardware and scheduling overhead determine elapsed time.',
            'eta':'Planning range: two qualified 4-core nodes 6-10h, one such node serial 12-20h including engineering/audit/eval/report; not a guarantee or deadline. Replace after first 256 committed games with segment clocks and remaining workload.'},
        'recovery': {
            'scientific_retries':0,'infrastructure_retries_per_unfinished_job':1,'whole_round_extra_attempts':128,
            'coordinator_restarts_per_node':6,'transfer_retries_per_object':6,
            'rules':'Verify node/PID/create_time/execution/source/weights/full optimizer+RNG+cursor; reconcile orphans; committed games and logical updates consumed once; cumulative CPU and failure history retained. Infrastructure repairs within this policy proceed without owner start confirmation.',
            'stop':'Completed finite workload, scientific invalidity, resource/attempt bound exhaustion, or user stop. Engineering/report failures get isolated source revision and bounded recovery; never rerun matches just to repair reports.',
            'persistent':'Install and verify process-independent stage/resume controller before first research game; session ending does not stop authorized progress. It terminates after R9.'},
        'observation': {
            'owner':'Luna subagent, not a second Sol', 'poll_seconds':3600,
            'event_checks':['child exit','failed commit','audit failure','stage transition'],
            'normal_progress_notifications':False,'idle_notifications':False,
            'notify_only':['concrete action only the owner can perform','whole-round final delivery'],
            'handling':'Local controller detects exits/hangs promptly; Luna is low-frequency independent review and recovery, not the only scheduler. Routine repairs proceed within bounds. Required owner intervention must state exact action; no hourly status spam.',
            'automatic_repair_scope':'Recover unchanged scientific work, transfer/report adapters and identity-preserving evidence repairs; never change mixture/seeds/checkpoint/gates/CPU caps.',
            'final':'Cancel or pause only this round monitor when delivered. Do not resurrect paused M79 reminders.'},
        'implementation': {
            'status':'NOT_IMPLEMENTED; plan generation and static validation only',
            'design_cli':'python scripts/prism_m81_plan.py --validate',
            'required_independent_adapters':['two-arm preparation/runtime and shared ledger','resource-bound execution without calendar deadline','strict full-state resume and source-revision handling','training heuristic descriptor support','two-arm final audit and freeze','new final grid and statistics','profile correction and readable report'],
            'code_references':['scripts/prism_m79_prepare.py','scripts/prism_m79_run.py','scripts/prism_m79_evaluate.py','scripts/prism_m79_audit.py','scripts/prism_m79_statistics.py','scripts/prism_m79_archive.py','training/prism_portable/engine/ppo/coordinator.py','training/prism_portable/engine/ppo/arena.py'],
            'preflight_required':['parent/all opponent byte SHA','frozen heuristic descriptor and golden action parity','rule/catalog/encoder/numeric parity','complete source snapshot and runtime hash','exact generated training/eval grids and global seed registry','no inherited calendar deadline at any layer','crash/resume preserves full state/counters/commits','training/audit full tensor inventory including style_head','report failure does not rerun games','actual node capacity and owned process identity','persistent controller stage handoff and observer ownership'],
            'source_policy':'Do not run M79 entrypoints unchanged or edit frozen deployed source. New isolated M81 source revision bound before first job. Resolve machine paths/hashes autonomously.',
            'runtime_parity':'Both arms use identical qualified numerical environment. Architecture/hyperparameters copied exactly from frozen M79 numeric blueprint; zero-new-game saved-fixture/optimizer/export/resume checks.',
            'required_owner_decisions':0},
        'delivery':['A/B fixed c20 + full final state + all checkpoint SHA','full logical/physical/CPU ledger','independent per-opponent both-seat results and all gates','diagnostic behaviors with actual denominators','candidate identities and intended uses','conclusion-first offline HTML + complete Markdown + technical audit','1440/390 actual pixel and interaction verification','private history archive/restore receipt','milestone/handoff/reports index and ALL or pending-sync'],
        'prohibited':['next unbounded round','retune from independent results','extra samples until significant','reward penalty for reserves','style reward','best-arm/checkpoint selection after test','automatic model release/default deployment','Git commit/push','machine shutdown'],
        'execution_contract':'Forwarded Sol instruction authorizes engineering→zero-game preflight→two-arm training→audit→frozen independent eval→profiles→report→R9. Do not stop at plan acknowledgement, preflight, c20 export, ALL failure, a missing second node, or an unresolved style label.'}
    return plan


def schedule(plan):
    training=[];evaluation=[]
    for arm, spec in plan['training']['arms'].items():
        for cycle in range(20):
            for block in range(128):
                for seat in [0,1]:
                    training.append({'arm':arm,'cycle':cycle+1,'seed':81001000+128*cycle+block,'seat':seat,'opponent':spec['opponent_period'][block%16]})
    for actor in plan['evaluation']['actors']:
        for opponent,(lo,hi) in plan['evaluation']['seed_by_opponent'].items():
            for seed in range(lo,hi+1):
                for seat in [0,1]:evaluation.append({'actor':actor,'opponent':opponent,'seed':seed,'seat':seat})
    lo,hi=plan['evaluation']['direct_parent']['seed_range']
    for actor in ['A','B']:
        for seed in range(lo,hi+1):
            for seat in [0,1]:evaluation.append({'actor':actor,'opponent':'parent','seed':seed,'seat':seat})
    return {'format':'prism-m81-logical-schedule-v1','training':training,'evaluation':evaluation}


def validate(plan, grid):
    for item in plan['inputs'].values():assert sha(ROOT/item['path'])==item['sha256'],item['path']
    for key,item in plan['assets'].items():
        if 'local_path' in item:assert sha(ROOT/item['local_path'])==item['sha256'],key
    t,e=grid['training'],grid['evaluation']
    assert len(t)==10240 and len(e)==14336
    assert len({(x['arm'],x['seed'],x['seat']) for x in t})==len(t)
    assert len({(x['actor'],x['opponent'],x['seed'],x['seat']) for x in e})==len(e)
    assert not {x['seed'] for x in t}&{x['seed'] for x in e}
    for arm in ['A','B']:
        rows=[r for r in t if r['arm']==arm]
        counts=Counter(r['opponent'] for r in rows)
        expected={o:1280 for o in set(A_ORDER)} if arm=='A' else {**{o:960 for o in set(A_ORDER)},'heuristic':640,'balance':640}
        assert counts==expected
        for cycle in range(1,21):
            assert len([r for r in rows if r['cycle']==cycle])==256
    bykey={(x['arm'],x['seed'],x['seat']):x for x in t}
    same=sum(x['opponent']==bykey['B',x['seed'],x['seat']]['opponent'] for x in t if x['arm']=='A')
    assert same==3840
    assert plan['training']['ppo']==json.loads((ROOT/plan['inputs']['m79_plan']['path']).read_text())['training']['ppo']
    assert 2*plan['resources']['training_cpu_seconds_per_arm']+plan['resources']['evaluation_cpu_seconds']+plan['resources']['audit_control_cpu_seconds']==plan['resources']['total_cpu_seconds']
    assert len(t)+len(e)+128==24704
    assert plan['resources']['absolute_stop'] is None and plan['resources']['round_elapsed_wall_stop'] is None
    # Check existing local benchmark numeric seeds; intentional sharing is only within M81.
    proposed={x['seed'] for x in t+e}|{81090001,81090002,81099999}
    conflicts=[]
    for p in (ROOT/'benchmarks').rglob('*.json'):
        if p.name.startswith('m81-'):continue
        hits=proposed & {int(v) for v in re.findall(r'(?<![A-Za-z0-9])\d{8,}(?![A-Za-z0-9])',p.read_text(encoding='utf-8'))}
        if hits:conflicts.append({'path':str(p.relative_to(ROOT)),'values':sorted(hits)})
    assert not conflicts,conflicts
    return {'status':'PASS_DESIGN_STATIC_CHECKS','scientific_execution':'NOT_RUN','new_games':0,
            'training_games':len(t),'evaluation_games':len(e),'logical_total':24576,'physical_ceiling':24704,
            'paired_same_opponent_training_slots':same,'replaced_slots':1280,
            'checks':['source and all neural asset SHA','A/B one mixture difference and same PPO','unique logical grids and two seats','disjoint train/eval seeds','local historical benchmark seed scan','counts and CPU arithmetic','no calendar or round elapsed stop'],
            'runtime_checks':'Sol must still implement/verify independent runtime, remote global seed registry, heuristic/runtime identity, resource admission and persistent recovery. Static PASS is not launch PASS.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--validate',action='store_true');args=p.parse_args()
    if args.write:
        plan=design();grid=schedule(plan);receipt=validate(plan,grid)
        write(PLAN_PATH,plan);write(ROOT/'benchmarks/m81-anchor-coverage.schedule.json',grid)
    else:
        plan=json.loads(PLAN_PATH.read_text(encoding='utf-8'));grid=json.loads((ROOT/'benchmarks/m81-anchor-coverage.schedule.json').read_text(encoding='utf-8'));receipt=validate(plan,grid)
        assert grid==schedule(plan)
    receipt.update({'plan_sha256':sha(PLAN_PATH),'schedule_sha256':sha(ROOT/'benchmarks/m81-anchor-coverage.schedule.json')})
    write(ROOT/'local-artifacts/prism/m81-anchor-coverage/plan-validation.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
