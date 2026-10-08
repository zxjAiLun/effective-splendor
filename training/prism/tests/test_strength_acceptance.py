"""Tests protect acceptance from reporting a failed/inconclusive gate as success."""
from scripts.prism_strength_acceptance import interval,strength_gates

GATES={'pooled_anchor_delta_lower_gt':0.0,'direct_duel_candidate_score_lower_gt':0.5,'per_anchor_delta_lower_gte':-0.05}

def values(pooled=0.03,duel=0.53,a=0.02,b=0.01):
 return {'pooled_delta':{'mean':0.09,'simultaneous_one_sided_lower':pooled},'direct_duel':{'mean':0.60,'simultaneous_one_sided_lower':duel},'anchor_deltas':{'heuristic-v031':{'simultaneous_one_sided_lower':a},'prism-v01':{'simultaneous_one_sided_lower':b}}}

def test_mean_improvement_cannot_pass_inconclusive_interval():
 r=strength_gates(values(pooled=-0.001),GATES)
 assert not all(r.values()) and not r['pooled_anchors_superiority']

def test_direct_duel_cannot_be_replaced_by_common_anchor_improvement():
 r=strength_gates(values(duel=0.49),GATES)
 assert not all(r.values()) and not r['direct_parent_superiority']

def test_one_anchor_regression_cannot_be_hidden_in_pool():
 r=strength_gates(values(a=-0.051),GATES)
 assert not all(r.values()) and not r['anchor_noninferiority/heuristic-v031']

def test_strict_superiority_and_noninferiority_thresholds():
 assert not strength_gates(values(pooled=0),GATES)['pooled_anchors_superiority']
 assert not strength_gates(values(duel=.5),GATES)['direct_parent_superiority']
 assert strength_gates(values(a=-.05),GATES)['anchor_noninferiority/heuristic-v031']
 assert all(strength_gates(values(),GATES).values())

def test_bootstrap_samples_whole_dual_seat_blocks_reproducibly():
 # Opposite seat results average to one half in every seed block.
 out=interval([.5]*16,1000,54039999,.0125)
 assert out=={'mean':.5,'ci95':[.5,.5],'simultaneous_one_sided_lower':.5}
 assert interval([0,0,.5,1,1],1000,54039999,.0125)==interval([0,0,.5,1,1],1000,54039999,.0125)
 assert interval([0,0,.5,1,1],1000,54039999,.0125)['simultaneous_one_sided_lower']<=interval([0,0,.5,1,1],1000,54039999,.0125)['ci95'][0]
