"""Small tests for goal selection and query boundaries; no real games or queries."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import m50_v031_goal_round as goal
import m50_teacher_query as query


def test_champion_keeps_parent_over_weaker_children_and_earlier_tie(tmp_path, monkeypatch):
    monkeypatch.setattr(goal, 'identity', lambda base, name: {'candidate': name})
    for name, score in [('parent', .4), ('a', .39), ('b', .45), ('c', .45)]:
        folder = tmp_path / name / 'development'
        folder.mkdir(parents=True)
        (folder / 'summary.json').write_text(json.dumps({'status': 'VALID', 'total_games': 512, 'score_rate': score}))
    assert goal.champion({}, tmp_path)['candidate'] == 'b'
    (tmp_path / 'b/development/summary.json').write_text(json.dumps({'status': 'VALID', 'total_games': 512, 'score_rate': .39}))
    (tmp_path / 'c/development/summary.json').write_text(json.dumps({'status': 'VALID', 'total_games': 512, 'score_rate': .4}))
    assert goal.champion({}, tmp_path)['candidate'] == 'parent'


def test_champion_rejects_incomplete_development(tmp_path, monkeypatch):
    monkeypatch.setattr(goal, 'identity', lambda base, name: {'candidate': name})
    folder = tmp_path / 'parent/development'
    folder.mkdir(parents=True)
    (folder / 'summary.json').write_text(json.dumps({'status': 'VALID', 'total_games': 511, 'score_rate': .8}))
    with pytest.raises(AssertionError):
        goal.champion({}, tmp_path)


def context():
    return {'offline': {'seed': 999999, 'source_replay': 'secret-source'}, 'player_view': {
        'actor': 0, 'observation': {'viewer': 0, 'public': {}, 'private': {}},
        'observation_hash': 'f' * 64, 'visible_history': [], 'legal_actions': [{'type': 'pass'}]}}


def report():
    return {'protocol_version': '0.5', 'engine_version': '0.4.0', 'ruleset': 'splendor-base-v1',
            'ruleset_fingerprint': 'a' * 64, 'seed_commitment': 'b' * 64}


def test_query_sends_no_offline_seed_and_preserves_true_action(monkeypatch):
    ctx = context()
    def run(argv, **kwargs):
        wire = kwargs['input']
        assert '999999' not in wire and 'secret-source' not in wire
        messages = [json.loads(line) for line in wire.splitlines()]
        assert [m['type'] for m in messages] == ['hello', 'game_start', 'observation', 'request_action']
        gid = messages[0]['game_id']
        replies = [{'type': 'hello', 'protocol_version': '0.5', 'game_id': gid},
                   {'type': 'action', 'protocol_version': '0.5', 'game_id': gid, 'request_id': 1, 'action': {'type': 'pass'}}]
        return SimpleNamespace(returncode=1, stdout='\n'.join(json.dumps(r) for r in replies), stderr='input closed')
    monkeypatch.setattr(query.subprocess, 'run', run)
    result = query.query_teacher('not-executed', [], ctx, report(), 'opaque')
    assert result['policy_target_idx'] == 0
    assert result['termination'].endswith('not_a_completed_game')
    assert ctx['offline']['seed'] == 999999


def test_query_rejects_referee_information_before_process(monkeypatch):
    ctx = context()
    ctx['player_view']['observation']['seed'] = 123
    monkeypatch.setattr(query.subprocess, 'run', lambda *a, **k: pytest.fail('process must not start'))
    with pytest.raises(AssertionError):
        query.query_teacher('not-executed', [], ctx, report(), 'opaque')


def test_query_rejects_illegal_teacher_response(monkeypatch):
    def run(argv, **kwargs):
        gid = json.loads(kwargs['input'].splitlines()[0])['game_id']
        replies = [{'type': 'hello', 'protocol_version': '0.5', 'game_id': gid},
                   {'type': 'action', 'protocol_version': '0.5', 'game_id': gid, 'request_id': 1, 'action': {'type': 'bad'}}]
        return SimpleNamespace(returncode=1, stdout='\n'.join(json.dumps(r) for r in replies), stderr='')
    monkeypatch.setattr(query.subprocess, 'run', run)
    with pytest.raises(AssertionError):
        query.query_teacher('not-executed', [], context(), report(), 'opaque')
