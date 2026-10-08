from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'scripts'))
from prism_building_policy_panel_m62 import policy_summary


def test_legal_action_multiplicity_mass_is_summed_and_conditional_is_separate():
    s = policy_summary(['buy_lowvp','take_tokens','buy_lowvp','buy_scoring'], [.1,.5,.2,.2])
    assert s['lowvp_mass'] == pytest.approx(.3)
    assert s['buy_conditional_lowvp'] == pytest.approx(.6)
    assert s['greedy_class'] == 'take_tokens'


def test_greedy_tie_uses_first_action_and_no_buy_is_explicit():
    s = policy_summary(['pass','take_tokens'], [.5,.5])
    assert s['greedy_class'] == 'pass'
    assert s['buy_conditional_lowvp'] is None


@pytest.mark.parametrize('classes,probs', [(['pass'],[.9]), (['pass'],[-1]), (['pass'],[float('nan')]), (['pass'],[.5,.5])])
def test_invalid_probabilities_rejected(classes, probs):
    with pytest.raises(ValueError):
        policy_summary(classes, probs)
