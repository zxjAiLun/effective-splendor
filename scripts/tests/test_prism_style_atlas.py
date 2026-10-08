import unittest
from scripts.prism_style_atlas import aggregate,classify,classify_profiles,grid_digest,midrank,read

class StyleBandsTest(unittest.TestCase):
    def setUp(self):
        self.policy=read('benchmarks/prism-style-bands-v1.policy.json')
        self.zero={k:0. for k in ['big_printed_vp','low_share','low_cards','first_big_main','first_big_coverage','early_low_cards','early_discount_redemptions','noble_coverage']}
    def profile(self):
        grid=[{'opponent':'d'*64,'seed':s,'seat':seat} for s in range(1,11) for seat in [0,1]]
        return dict(self.zero,sha256=self.policy['reference_sha256'],mode='both-greedy',opponent_fixture=['d'*64],seed_start=1,seed_end=10,seats=[0,1],rules_sha256='a'*64,observed_grid=grid,observed_grid_sha256=grid_digest(grid),metrics_semantics='own-Main-12-24-v1',games=20,missing_games=0)
    def test_unmatched_reference_rejected(self):
        self.assertEqual(classify(self.zero,self.policy,False)['route'],'undetermined')
    def test_current_baseline_accepts_b_and_rejects_old_balance(self):
        policy=read('benchmarks/prism-style-bands-v020.policy.json')
        ref=self.profile();candidate=dict(ref,sha256='c'*64)
        self.assertEqual(classify_profiles(candidate,ref,policy)['level'],'INSUFFICIENT')
        ref['sha256']=policy['reference_sha256']
        self.assertEqual(classify_profiles(candidate,ref,policy)['route'],'Balance')
    def test_current_baseline_does_not_fill_missing_timing(self):
        policy=read('benchmarks/prism-style-bands-v020.policy.json')
        ref=self.profile();ref['sha256']=policy['reference_sha256'];ref['first_big_main']=None
        result=classify_profiles(dict(ref,sha256='c'*64),ref,policy)
        self.assertEqual(result['level'],'INSUFFICIENT')
    def test_missing_timing_not_default_balance(self):
        self.assertEqual(classify({'low_share':0,'big_printed_vp':0},self.policy,True)['level'],'INSUFFICIENT')
    def test_positive_balance_and_border_overlap(self):
        self.assertEqual(classify(self.zero,self.policy,True)['route'],'Balance')
        d=dict(self.zero,big_printed_vp=.5,low_share=-.02,first_big_main=-1.)
        self.assertEqual(classify(d,self.policy,True)['route'],'mixed')
    def test_alpha_requires_timing_and_coverage(self):
        d=dict(self.zero,big_printed_vp=.7,low_share=-.03,first_big_main=-2.)
        self.assertEqual(classify(d,self.policy,True)['route'],'Alpha')
        d['first_big_coverage']=-.06
        self.assertEqual(classify(d,self.policy,True)['route'],'undetermined')
    def test_beta_requires_real_investment_redemption(self):
        d=dict(self.zero,low_share=.03,low_cards=.4,early_low_cards=.4)
        self.assertEqual(classify(d,self.policy,True)['route'],'undetermined')
        d['early_discount_redemptions']=.4
        self.assertEqual(classify(d,self.policy,True)['route'],'Beta')
    def test_midrank_ties(self):
        self.assertEqual(midrank(1,[1,1,1]),.5)
        self.assertEqual(midrank(2,[1,2,3]),.5)
    def test_same_metrics_wrong_seeds_or_reference_rejected(self):
        ref=self.profile()
        candidate=dict(ref,sha256='c'*64)
        self.assertEqual(classify_profiles(candidate,ref,self.policy)['route'],'Balance')
        candidate['seed_end']=11
        self.assertEqual(classify_profiles(candidate,ref,self.policy)['route'],'undetermined')
    def test_route_specific_missing_is_visible(self):
        d=dict(self.zero,big_printed_vp=.7,low_share=-.03,first_big_main=-2.,early_discount_redemptions=None)
        r=classify(d,self.policy,True)
        self.assertEqual(r['route'],'undetermined')
        self.assertEqual(r['provisional_hits'],['Alpha'])
        self.assertEqual(r['missing_by_route']['Alpha'],[])
        self.assertEqual(r['missing_by_route']['Beta'],['early_discount_redemptions'])
    def test_nonfinite_and_boolean_inputs_are_missing(self):
        for value in [float('nan'),float('inf'),True,'0']:
            self.assertEqual(classify(dict(self.zero,low_share=value),self.policy,True)['level'],'INSUFFICIENT')
    def test_same_seed_bounds_different_grid_rejected(self):
        ref=self.profile()
        for change in [{'observed_grid_sha256':'d'*64},{'missing_games':1},{'sha256':'candidate'},{'mode':'sampling'},{'games':19},{'metrics_semantics':'unknown'}]:
            self.assertEqual(classify_profiles(dict(ref,**change),ref,self.policy)['level'],'INSUFFICIENT')
    def test_duplicate_grid_rejected_even_with_recomputed_digest(self):
        ref=self.profile();grid=ref['observed_grid'][:-1]+[ref['observed_grid'][0]]
        altered=dict(ref,observed_grid=grid,observed_grid_sha256=grid_digest(grid))
        self.assertEqual(classify_profiles(altered,altered,self.policy)['level'],'INSUFFICIENT')
    def test_observed_grid_order_does_not_change_identity(self):
        ref=self.profile();candidate=dict(ref,observed_grid=list(reversed(ref['observed_grid'])))
        self.assertEqual(classify_profiles(candidate,ref,self.policy)['route'],'Balance')
    def test_pooled_denominators(self):
        def m(n,c,main):return {'games':n,'mean_cards_by_vp':dict(zip(map(str,range(6)),c)), 'games_with_nobles':n//2,'mean_prestige':15,'total_main_actions':main}
        a=aggregate([m(2,[1,0,0,0,0,1],20),m(6,[3,0,0,0,0,1],60)])
        self.assertEqual(a['low_cards'],2.5);self.assertAlmostEqual(a['low_share'],2.5/3.5)
        self.assertEqual(a['vp_main'],1.5)

if __name__=='__main__':unittest.main()
