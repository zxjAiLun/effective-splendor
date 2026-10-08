import importlib.util
from pathlib import Path
import statistics

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('m62_training_diag', ROOT / 'scripts/prism_building_training_diagnostic_m62.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def test_constant_style_offset_is_removed_by_joint_centering():
    result = diag.advantage_summary([-1, 0, 1], [.5, .5, .5], .3)
    assert result['combined']['mean'] == pytest.approx(.15)
    assert result['centered_style_std_over_combined_std'] == 0
    assert result['normalized_mean_absolute_change'] == pytest.approx(0, abs=1e-15)
    assert result['centered_sign_flip_count'] == 0


def test_covariance_and_centered_sign_change_are_preserved():
    left, residual = [-.1, .1, .2], [1, -1, -1]
    result = diag.advantage_summary(left, residual, .3)
    combined = [x + .3*y for x, y in zip(left, residual)]
    assert result['combined']['std'] == pytest.approx(statistics.pstdev(combined))
    assert result['covariance_outcome_weighted_style'] < 0
    assert result['centered_sign_flip_count'] > 0


def test_zero_variance_is_explicit_and_alignment_rejected():
    assert diag.advantage_summary([0,0], [0,0], 0)['centered_style_std_over_combined_std'] is None
    with pytest.raises(ValueError):
        diag.advantage_summary([0], [0,1], .3)


def test_panel_uses_semantic_target_vp_and_keeps_action_order():
    row = {'legal_actions': [{'type': 'buy_market', 'vp': 1}, {'type': 'take_tokens'},
                             {'type': 'buy_reserved', 'vp': 4}],
           'request': {'input': {'actions': [[], [], []]}}, 'observation': {}}
    def target(obs, action):
        return 4, ('One', 0, action['vp'], (0,0,0,0,0))
    assert diag.action_classes(row, target) == ['buy_lowvp', 'take_tokens', 'buy_scoring']
    row['request']['input']['actions'].pop()
    with pytest.raises(ValueError, match='mismatch'):
        diag.action_classes(row, target)


def test_quantiles_are_linear_interpolated_with_population_std():
    result = diag.distribution([0, 2, 4, 6])
    assert result['median'] == 3
    assert result['p10'] == pytest.approx(.6)
    assert result['std'] == pytest.approx(statistics.pstdev([0,2,4,6]))
