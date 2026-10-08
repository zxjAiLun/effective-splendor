"""Protect finite second-look acceptance from optional stopping and weaker gates."""
from copy import deepcopy
import pytest
from scripts.prism_strength_confirmation import confirmation_seeds,expected_grid

BASE={
 'format':'m54-prism-strength-confirmation-v2',
 'holdout':{'seed_start':9470000,'seed_end':9470511,'seeds':512,'total_formal_games':5120,'direct_duel_games':1024,'anchor_total_games':4096},
 'statistics':{'family_alpha':.05,'evaluation_look':2,'maximum_evaluation_looks':2,'one_sided_gate_count':4,'bonferroni_lower_quantile':.00625,'samples':20000,'seed':54049999,'single_final_analysis_no_optional_stopping':True},
 'budget':{'max_formal_games':5120,'max_physical_attempts':5120,'infra_retries':0,'local_match_workers':4,'campaign_wall_hours':6},
 'gates':{'pooled_anchor_delta_lower_gt':0.0,'direct_duel_candidate_score_lower_gt':.5,'per_anchor_delta_lower_gte':-.05,'all_four_strength_gates_required':True},
 'sampling':{'action_seed':54030001,'no_inference_overlay':True},
}

@pytest.mark.parametrize('section,key,value',[
 ('statistics','bonferroni_lower_quantile',.0125),
 ('statistics','maximum_evaluation_looks',3),
 ('statistics','single_final_analysis_no_optional_stopping',False),
 ('budget','max_physical_attempts',5121),
 ('budget','infra_retries',1),
 ('holdout','seed_start',9450000),
 ('gates','direct_duel_candidate_score_lower_gt',.49),
 ('sampling','no_inference_overlay',False),
])
def test_confirmation_rejects_weakening_or_new_attempts(section,key,value):
 cfg=deepcopy(BASE);cfg[section][key]=value
 with pytest.raises(ValueError):confirmation_seeds(cfg)

def test_two_seat_grid_has_all_models_and_comparators_without_prior_seeds():
 seeds=confirmation_seeds(BASE);keys=expected_grid(seeds)
 assert len(keys)==5120
 assert sum(k[1]=='parent-t1' for k in keys)==1024
 assert {k[2] for k in keys}==set(range(9470000,9470512))
 assert {k[3] for k in keys}=={0,1}
