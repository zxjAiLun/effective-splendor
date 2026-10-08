import copy
import importlib
import json
import math
from pathlib import Path
import pytest
import numpy as np
from scripts import prism_rush_round as round
from scripts import prism_rush_report as report


def fixture():
    stats=round.read(round.PILOT)['acceptance'];stats=copy.deepcopy(stats)
    stats.update(seed_start=1,seed_end=8,bootstrap_samples=200)
    rows=[]
    for model,op,seed,seat in sorted(round.expected_grid(1,8)|round.expected_grid(1,8,True)):
        rows.append({'candidate':model,'opponent':op,'seed':seed,'candidate_seat':seat,
                     'candidate_score': (.5 if seat==0 else 1.) if model=='rush' else .5,
                     'rush_auc':.35 if model=='rush' else .25,
                     'vp_threshold_by_horizon':model=='rush'})
    return stats,rows


def test_all_gates_require_both_strength_and_style():
    stats,rows=fixture();values,gates=round.measurements(rows,stats)
    assert len(gates)==6 and all(gates.values())
    assert math.isclose(values['rush_auc']['mean'],.1)
    for r in rows:
        if r['candidate']=='rush':r['rush_auc']=.25
    values,gates=round.measurements(rows,stats)
    assert not gates['rush_auc'] and all(v for k,v in gates.items() if k!='rush_auc')


def test_strength_failure_preserved_despite_clear_style():
    stats,rows=fixture()
    for r in rows:
        if r['candidate']=='rush':r['candidate_score']=0
    _,gates=round.measurements(rows,stats)
    assert gates['rush_auc'] and gates['vp8_by_main20']
    assert not gates['strength_pool'] and not gates['direct_base']


@pytest.mark.parametrize('bad',['duplicate','missing','extra','seat'])
def test_incomplete_or_ambiguous_grid_rejected(bad):
    stats,rows=fixture()
    if bad=='duplicate':rows.append(dict(rows[0]))
    elif bad=='missing':rows.pop()
    elif bad=='extra':rows[0]['seed']=99
    else:rows[0]['candidate_seat']=2
    with pytest.raises(ValueError,match='grid'):round.measurements(rows,stats)


def test_nonfinite_measurement_rejected():
    stats,rows=fixture();rows[-1]['rush_auc']=float('nan')
    with pytest.raises(ValueError,match='invalid paired'):round.measurements(rows,stats)


def test_paired_block_order_is_irrelevant():
    stats,rows=fixture()
    for r in rows:
        r['candidate_score']=float((r['seed']+r['candidate_seat'])%2) if r['candidate']=='rush' else .5
    a=round.measurements(rows,stats)
    b=round.measurements(list(reversed(rows)),stats)
    assert a==b


def test_readable_tables_use_measured_model_and_both_players():
    d=round.read(round.ROOT/'benchmarks/m54-prism-011.match-details.json')
    pairs=[]
    for p in d['pairs']:
        p=copy.deepcopy(p);p['candidate']='rush' if p['candidate']=='c8' else 'base'
        if p['opponent']=='parent-t1':p['opponent']='base-t1'
        p.update(mean_rush_auc=.2,vp8_by_main20_rate=.3,short_game_fraction=0)
        pairs.append(p)
    text=report.detailed_tables(pairs,'offline fixture only')
    assert 'Prism v0.1.1' in text and 'Prism Rush v0.1.0' in text
    assert '(011)' not in text and 'trial-v1 c8 parent' not in text
    assert 'NOT_MEASURED / NOT_MEASURED' in text
    assert all(x in text for x in ['买市场','买预留','取宝石','预留市场','预留牌堆','选贵族','跳过','0 VP卡','5 VP卡','终局未买回预留'])
    assert '609 / 9 / 406' in text


def test_strict_style_gate_does_not_accept_equality():
    stats,rows=fixture()
    values,_=round.measurements(rows,stats)
    stats['rush_auc_delta_lower_gt']=values['rush_auc']['simultaneous_one_sided_lower']
    stats['vp8_by_main20_rate_delta_lower_gt']=values['vp8_by_main20']['simultaneous_one_sided_lower']
    _,gates=round.measurements(rows,stats)
    assert not gates['rush_auc'] and not gates['vp8_by_main20']


def test_future_plan_covers_exact_budget_without_running_game(tmp_path,monkeypatch):
    import shutil
    monkeypatch.setattr(round,'ART',tmp_path)
    final=tmp_path/'campaign/cycle-4-export/weights.json';final.parent.mkdir(parents=True)
    pilot=round.read(round.PILOT);train=round.read(round.TRAIN)
    shutil.copyfile(round.ROOT/pilot['base_model']['weights_path'],final)
    for stage in ('development','acceptance'):
        plan=round.make_plan(stage,pilot,train)
        keys=set()
        for shard in plan['shards']:
            cfg=round.read(shard['config'])
            keys.update((m,o,seed,seat) for m in cfg['candidates'] for o in cfg['opponents'] for seed in cfg['seeds'] for seat in (0,1))
        segment=pilot[stage]
        expected=round.expected_grid(segment['seed_start'],segment['seed_end'])
        if stage=='acceptance':expected|=round.expected_grid(segment['seed_start'],segment['seed_end'],True)
        assert keys==expected and sum(s['games'] for s in plan['shards'])==segment['total_games']
        assert not any(Path(s['output']).exists() for s in plan['shards'])
