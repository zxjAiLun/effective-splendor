import unittest
from scripts.prism_style_history import conditional_timing


class HistoricalTimingTests(unittest.TestCase):
    def test_conditional_mean_uses_purchase_coverage(self):
        pairs=[{'candidate_metrics':{'games':100},'candidate_bigcard':{'games':100,'first_4plus_card_main':{'coverage_games':10,'conditional_mean':10}}},
               {'candidate_metrics':{'games':100},'candidate_bigcard':{'games':100,'first_4plus_card_main':{'coverage_games':90,'conditional_mean':20}}}]
        r=conditional_timing(pairs,'candidate')
        self.assertEqual(r['first_big_main'],19)
        self.assertEqual(r['first_big_coverage'],.5)

    def test_missing_timing_never_becomes_zero(self):
        r=conditional_timing([{'opponent_metrics':{'games':100}}],'opponent')
        self.assertIsNone(r['first_big_main'])
        self.assertIsNone(r['first_big_coverage'])

    def test_no_purchase_keeps_zero_coverage_and_unmeasured_time(self):
        r=conditional_timing([{'candidate_metrics':{'games':100},'candidate_bigcard':{'games':100,'first_4plus_card_main':{'coverage_games':0,'conditional_mean':None}}}],'candidate')
        self.assertEqual(r['first_big_coverage'],0)
        self.assertIsNone(r['first_big_main'])


if __name__=='__main__':unittest.main()
