"""The amendment may archive only the two exact interrupted partials."""
import copy

import pytest

from scripts import prism_alpha_cloud_evaluation_repair as repair


@pytest.fixture
def partials(tmp_path):
    allowed = []
    for i in range(2):
        path = tmp_path / 'acceptance/runs/shard/games/base/opponent' / f'seed-{i}-seat-0'
        path.mkdir(parents=True)
        repair.write(path / 'game.json', {'status': 'running'})
        allowed.append({'path': str(path), 'hashes': {'game.json': repair.sha(path / 'game.json')}})
    return tmp_path, {'completed_acceptance_commits': 1817, 'interrupted_acceptance_games': allowed}


def test_exact_two_partials_pass_without_mutation(partials):
    work, incident = partials
    before = copy.deepcopy(incident)
    assert len(repair.partial_guard(work, incident)) == 2
    assert incident == before


def test_completed_game_cannot_be_archived(partials):
    work, incident = partials
    path = work / 'acceptance/runs/shard/games/base/opponent/seed-0-seat-0/game.json'
    repair.write(path, {'status': 'completed'})
    incident['interrupted_acceptance_games'][0]['hashes']['game.json'] = repair.sha(path)
    with pytest.raises(ValueError, match='completed game'):
        repair.partial_guard(work, incident)


def test_hash_drift_blocks_resume(partials):
    work, incident = partials
    incident['interrupted_acceptance_games'][0]['hashes']['game.json'] = '0' * 64
    with pytest.raises(ValueError, match='artifact drift'):
        repair.partial_guard(work, incident)


def test_scope_and_directory_escape_blocked(partials):
    work, incident = partials
    bad = copy.deepcopy(incident)
    bad['interrupted_acceptance_games'][0]['path'] = str(work.parent / 'foreign')
    with pytest.raises(ValueError, match='outside owned'):
        repair.partial_guard(work, bad)
    bad = copy.deepcopy(incident)
    bad['interrupted_acceptance_games'].pop()
    with pytest.raises(ValueError, match='incident scope'):
        repair.partial_guard(work, bad)
