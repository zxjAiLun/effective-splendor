import unittest
from scripts.prism_style_distributions import histogram, quantile
from scripts.prism_style_atlas import midrank


class DistributionTests(unittest.TestCase):
    def test_maximum_and_zero_are_observations(self):
        h=histogram([0,0,.5,1],2)
        self.assertEqual(h['counts'],[2,2])
        self.assertEqual(sum(h['counts']),h['n'])
        self.assertEqual(h['mean'],.375)

    def test_constant_sample_retains_all_counts(self):
        h=histogram([.6]*3)
        self.assertEqual(sum(h['counts']),3)
        self.assertEqual(h['median'],.6)
        self.assertLess(h['min'],.6)
        self.assertGreater(h['max'],.6)

    def test_quantile_and_tied_percentile(self):
        self.assertEqual(quantile([1,0,0,.5],.5),.25)
        self.assertEqual(quantile([1,0,0,.5],1),1)
        self.assertEqual(midrank(0,[0,0,.5,1]),.25)

    def test_missing_is_rejected_instead_of_zero_filled(self):
        for values in [[],[None],[float('nan')],[True]]:
            with self.assertRaises(ValueError):histogram(values)


if __name__=='__main__':unittest.main()
