"""M61 finite-grid and paired statistical contracts; never dispatch real games."""
import copy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from scripts import prism_balance_ab_evaluation_m61 as m
from scripts.prism_cloud_storage_snapshot import storage_bytes


def policy():
    return {'development': dict(seed_start=9616000, seed_end=9616031, total_games=576,
                                action_seed=m.ACTION_SEED, anchors=list(m.ANCHORS)),
            'acceptance': dict(seed_start=9621000, seed_end=9621255, direct_seed_end=9621511,
                total_games=7680, action_seed=m.ACTION_SEED, anchors=list(m.ANCHORS),
                one_sided_claims=0, simultaneous_comparisons=7, interval_sides='two-sided',
                family_alpha=.05, lower_quantile=m.LOWER_Q, upper_quantile=1-m.LOWER_Q,
                bootstrap_samples=20000, bootstrap_rng_seed=61039999,
                strength_pool_delta_lower_gte=-.05, direct_parent_score_lower_gte=.45,
                bigcard_auc24_delta_lower_gte=-.015, balance_alpha_pool_delta_lower_gt=0,
                balance_alpha_direct_score_lower_gt=.5, alpha_balance_pool_delta_upper_lt=0,
                alpha_balance_direct_score_upper_lt=.5, no_extension_or_checkpoint_selection=True)}


def rows_for(balance_delta=.1, direct=.7, alpha_style=.03, balance_style=-.8):
    s = policy()['acceptance']
    rows = []
    grid = m.expected_grid(s['seed_start'], s['seed_end']) | m.expected_grid(s['seed_start'], s['direct_seed_end'], True)
    for model, op, seed, seat in sorted(grid):
        # Seat effects cancel within the same identity's seed block.
        score = {'base': .5, 'alpha': .6, 'balance': .6 + balance_delta}[model] + (.1 if seat == 0 else -.1)
        if op == 'base-t1': score = .6 + (.1 if seat == 0 else -.1)
        if op == 'alpha-t1': score = direct + (.1 if seat == 0 else -.1)
        rows.append(dict(candidate=model, opponent=op, seed=seed, candidate_seat=seat,
                         candidate_score=score, large_card_vp_auc24={'base': 1., 'alpha': 1+alpha_style,
                                                                  'balance': 1+balance_style}[model]))
    return rows


def exact_intervals(vectors, stats):
    return {key: dict(mean=float(np.mean(v)), ci95=[float(np.mean(v))]*2,
                     simultaneous_lower=float(np.mean(v)), simultaneous_upper=float(np.mean(v)),
                     simultaneous_two_sided_ci=[float(np.mean(v))]*2, seed_blocks=len(v))
            for key, v in vectors.items()}


def test_full_grid_no_duplicate_base_or_reverse_ab():
    seen_stages = []
    for stage in ('development', 'acceptance'):
        cs = {x: {} for x in m.MODELS}; ops = {x: {} for x in m.ANCHORS}
        shards = m.shard_configs(stage, policy(), {'path': '/engine', 'sha256': 'a'*64}, 'catalog', cs, ops)
        keys = [(model, op, seed, seat) for _, _, cfg, _ in shards for model in cfg['candidates']
                for op in cfg['opponents'] for seed in cfg['seeds'] for seat in (0, 1)]
        assert len(keys) == len(set(keys)) == policy()[stage]['total_games']
        assert len(shards) == (2 if stage == 'development' else 40)
        assert sum(k[0] == 'base' for k in keys) == (192 if stage == 'development' else 1536)
        if stage == 'acceptance':
            assert sum(k[1] == 'base-t1' for k in keys) == 2048
            assert sum(k[:2] == ('balance', 'alpha-t1') for k in keys) == 1024
            assert all(k[1] != 'balance-t1' for k in keys)
        seen_stages.append(set(keys))
    assert not seen_stages[0].intersection(seen_stages[1])


@pytest.mark.parametrize('field,bad', [('one_sided_claims',7),('simultaneous_comparisons',5),
    ('lower_quantile',.05/7),('upper_quantile',.975),('bigcard_auc24_delta_lower_gte',0),
    ('direct_parent_score_lower_gte',.5),('strength_pool_delta_lower_gte',0),
    ('bootstrap_rng_seed',59039999),('bootstrap_samples',10000),('interval_sides','one-sided'),
    ('no_extension_or_checkpoint_selection',False)])
def test_reject_changed_frozen_family_thresholds(field, bad):
    p = policy(); p['acceptance'][field] = bad
    with pytest.raises(ValueError): m.validate_policy(p)


@pytest.mark.parametrize('delta,direct,verdict',[(.1,.7,'CONFIRMED_BALANCE_SUPERIOR'),
    (-.1,.3,'CONFIRMED_ALPHA_SUPERIOR'),(.1,.5,'INCONCLUSIVE'),(-.1,.7,'INCONCLUSIVE')])
def test_identity_seat_and_symmetric_ab_direction(delta, direct, verdict):
    rows = rows_for(delta, direct)
    with patch.object(m, 'joint_intervals', side_effect=exact_intervals):
        out, gates, comparison = m.measurements(rows, policy()['acceptance'])
        reordered = m.measurements(list(reversed(rows)), policy()['acceptance'])
    assert (out, gates, comparison) == reordered
    assert len(out) == 7 and len(gates) == 5
    assert 'balance/bigcard_auc24' not in out and 'balance/bigcard_auc24' not in gates
    assert out['alpha/strength_pool']['mean'] == pytest.approx(.1)
    assert out['balance_vs_alpha/strength_pool']['mean'] == pytest.approx(delta)
    assert out['balance_vs_alpha/direct']['mean'] == pytest.approx(direct)
    assert out['alpha/strength_pool']['seed_blocks'] == 256
    assert out['alpha/direct_parent']['seed_blocks'] == 512
    assert comparison['verdict'] == verdict
    assert all(gates.values())  # Balance's negative style profile is not an acceptance veto.


def test_alpha_style_floor_is_required_but_balance_style_is_descriptive():
    with patch.object(m, 'joint_intervals', side_effect=exact_intervals):
        _, gates, _ = m.measurements(rows_for(alpha_style=-.02, balance_style=.5), policy()['acceptance'])
    assert gates['alpha/bigcard_auc24'] is False
    assert gates['balance/strength_pool'] is True and gates['balance/direct_parent'] is True


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'wrong_seat'])
def test_reject_incomplete_duplicate_or_wrong_seat_grid(mutation):
    rows = rows_for()
    if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'missing': rows.pop()
    else: rows[0]['candidate_seat'] = 2
    with pytest.raises(ValueError, match='grid'):
        m.measurements(rows, policy()['acceptance'])


def test_joint_draws_and_two_sided_quantiles():
    stats = dict(bootstrap_rng_seed=61039999, bootstrap_samples=2000,
                 lower_quantile=m.LOWER_Q, upper_quantile=1-m.LOWER_Q)
    x = np.linspace(-1, 1, 256)
    out = m.joint_intervals({'positive': x, 'negative': -x, 'shifted': x+3, 'direct': np.ones(512)}, stats)
    assert out['negative']['simultaneous_lower'] == pytest.approx(-out['positive']['simultaneous_upper'])
    assert out['shifted']['simultaneous_lower'] == pytest.approx(out['positive']['simultaneous_lower']+3)
    assert out['positive']['simultaneous_lower'] <= out['positive']['ci95'][0]
    assert out['positive']['simultaneous_upper'] >= out['positive']['ci95'][1]
    assert out['direct']['simultaneous_two_sided_ci'] == [1.,1.]
    assert out == m.joint_intervals({'positive': x, 'negative': -x, 'shifted': x+3, 'direct': np.ones(512)}, stats)


def test_collector_adapter_restores_globals_even_on_failure(tmp_path):
    saved = m.alpha.ART, m.alpha.ROOT, m.alpha.expected_grid
    with pytest.raises(RuntimeError):
        with m.collector_adapter(tmp_path):
            assert m.alpha.expected_grid is m.expected_grid
            assert m.alpha.MODELS == ('base','alpha','balance')
            assert m.alpha.ART == tmp_path
            raise RuntimeError('audit failed')
    assert (m.alpha.ART, m.alpha.ROOT, m.alpha.expected_grid) == saved


def test_descriptive_pure_win_ci_counts_wins_not_half_draws():
    rows = [dict(seed=s, candidate_seat=seat, candidate_score=.5 if seat else 1.,
                 record='draw' if seat else 'win') for s in range(4) for seat in (0,1)]
    assert m.descriptive_ci(rows)['mean'] == .75
    win = m.descriptive_ci(rows, True)
    assert win['mean'] == .5 and win['ci95'] == [.5,.5]
    assert win['rng_seed'] == 61039999 and win['seed_blocks'] == 4


def test_storage_monitor_uses_safe_shared_helper(tmp_path):
    assert m.storage_bytes is storage_bytes
    stable = tmp_path/'data'; stable.write_bytes(b'123')
    with patch.object(Path,'rglob',return_value=iter([stable,tmp_path/'missing.tmp'])):
        assert m.storage_bytes(tmp_path) == 3
    assert 'prism_cloud_storage_snapshot.py' in m.HELPERS
    assert 'prism_balance_ab_report_m61.py' in m.HELPERS


def test_campaign_path_comes_from_contract_and_is_owned(tmp_path):
    p = {'training': {'arms': {'alpha': {'campaign': str(tmp_path/'campaigns/m61-alpha-ab-g0')}}}}
    assert m.arm_path(tmp_path,p,'alpha') == tmp_path/'campaigns/m61-alpha-ab-g0/cycle-4-export/weights.json'
    p['training']['arms']['alpha']['campaign'] = str(tmp_path.parent/'outside')
    with pytest.raises(ValueError,match='owned'): m.arm_path(tmp_path,p,'alpha')


def audited_project(tmp_path):
    inputs = tmp_path/'inputs'; inputs.mkdir()
    for name in ('parent.json','general.json','initial.json','fixtures.jsonl'):
        (inputs/name).write_text(name)
    (tmp_path/'scripts').mkdir()
    for name in m.HELPERS: (tmp_path/'scripts'/name).write_text('pinned helper '+name)
    engine = tmp_path/'engine'; engine.write_text('native')
    native = dict(path=str(engine),sha256=m.sha(engine))
    p = dict(evaluation=policy(),runtime=dict(cloud_root=m.CLOUD,engine=native,metrics=native,bigcard_metrics=native),
             base_model=dict(sha256=m.sha(inputs/'parent.json')),
             assets={name:dict(sha256=m.sha(inputs/(name+('.jsonl' if name=='fixtures' else '.json'))))
                     for name in ('parent','general','initial','fixtures')},training=dict(arms={}))
    p['evaluation']['native_path_and_sha256'] = native
    audit = dict(format='m61-training-audit-binding-v1',status='PASS_TRAINING_ARTIFACT_AUDIT',
                 initial_policy_value_and_rng_equal=True,completed_games=2048,arms={})
    for arm in ('alpha','balance'):
        campaign = tmp_path/f'campaigns/m61-{arm}-ab-g0'; (campaign/'cycle-4-export').mkdir(parents=True)
        (campaign/'control').mkdir(); (campaign/'cycle-4-export/weights.json').write_text(arm+'weights')
        bp = tmp_path/f'{arm}-train.json'
        m.write(bp,dict(template=dict(run=dict(catalog_fingerprint='catalog',style={'window_main_actions':24}),opponents={})))
        p['training']['arms'][arm] = dict(blueprint_path=str(bp),blueprint_sha256=m.sha(bp),campaign=str(campaign))
    config = tmp_path/m.CONFIG; config.parent.mkdir(); m.write(config,p); digest = m.sha(config)
    for arm in ('alpha','balance'):
        weights = m.sha(m.arm_path(tmp_path,p,arm)); work = tmp_path/f'audit-{arm}'; work.mkdir()
        checkpoint = dict(status='PASS',arm=arm,final_weights_sha256=weights,config_sha256=digest,
                          blueprint_sha256=p['training']['arms'][arm]['blueprint_sha256'])
        parity = dict(status='PASS',arm=arm,weights_sha256=weights,config_sha256=digest)
        status = dict(status='STOPPED_COMMITTED',resources=dict(returncode=0,stop_reason=None))
        ledger = work/'ledger.json'
        m.write(ledger,dict(arm=arm,candidate_sha256=weights,config_sha256=digest,
                           rows=[dict(job_id=str(i)) for i in range(1024)]))
        ld = dict(path=str(ledger),sha256=m.sha(ledger))
        full = dict(status='PASS_TRAINING_ARTIFACT_AUDIT',arm=arm,candidate_sha256=weights,
                    checkpoint=checkpoint,supervisor=status,completed_games=1024,source_ledger=ld)
        evidence = {'source_ledger':ld}
        for name, raw in [('checkpoint',checkpoint),('parity',parity),('full_training',full),('campaign_status',status)]:
            path = Path(p['training']['arms'][arm]['campaign'])/'control/status.json' if name=='campaign_status' else work/(name+'.json')
            m.write(path,raw); evidence[name] = dict(path=str(path),sha256=m.sha(path))
        audit['arms'][arm] = dict(candidate_sha256=weights,config_sha256=digest,evidence=evidence)
    path = tmp_path/'training-artifact-audit.json'; m.write(path,audit)
    return p,digest,path


def test_prepare_verify_full_virtual_project_runs_zero_games(tmp_path):
    _, digest, audit_path = audited_project(tmp_path)
    with patch.object(m.subprocess,'Popen') as launch, patch.object(Path, 'symlink_to',
            lambda link, target: link.write_bytes(Path(target).read_bytes())):
        m.prepare(tmp_path,digest,audit_path)
        execution = m.read(tmp_path/'evaluation/execution.json')
        m.verify(tmp_path/'evaluation',execution)
    launch.assert_not_called()
    assert set(execution['candidates']) == set(m.MODELS)
    assert execution['balance_style_acceptance'] == 'NOT_CLAIMED'
    assert len(m.read(tmp_path/'evaluation/acceptance/plan.json')['shards']) == 40
    raw = m.read(audit_path)
    for arm in ('alpha','balance'):
        for evidence in raw['arms'][arm]['evidence'].values():
            assert execution['files'][evidence['path']] == evidence['sha256']
    with pytest.raises(ValueError,match='already prepared'): m.prepare(tmp_path,digest,audit_path)


@pytest.mark.parametrize('mutation',['raw_status','weight','ledger_coverage','status_copy'])
def test_audit_binding_rechecks_raw_receipts_even_if_summary_says_pass(tmp_path, mutation):
    p,digest,path = audited_project(tmp_path)
    audit = m.read(path); evidence = audit['arms']['balance']['evidence']
    name = 'source_ledger' if mutation=='ledger_coverage' else 'campaign_status' if mutation=='status_copy' else 'parity'
    raw_path = Path(evidence[name]['path']); raw = m.read(raw_path)
    if mutation=='raw_status': raw['status']='FAIL'
    elif mutation=='weight': raw['weights_sha256']='0'*64
    elif mutation=='ledger_coverage': raw['rows'].pop()
    else: raw['status']='FAILED'
    m.write(raw_path,raw)
    # Updating the outer hash cannot turn a failed/inconsistent raw audit into PASS.
    evidence[name]['sha256']=m.sha(raw_path); m.write(path,audit)
    with pytest.raises(ValueError): m.bindings(tmp_path,digest,path)


def test_run_refuses_repeat_before_monitor_or_dispatch(tmp_path):
    work = tmp_path/'evaluation'; work.mkdir()
    (work/'once-only.lock').write_text('old failed run')
    m.write(work/'execution.json',{})
    with patch.object(m,'verify'), patch.object(m,'Monitor') as monitor, patch.object(m.subprocess,'Popen') as launch:
        with pytest.raises(FileExistsError): m.run(tmp_path,m.sha(work/'execution.json'))
    monitor.assert_not_called(); launch.assert_not_called()
