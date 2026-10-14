import unittest
from scripts.prism_m79_regression_diagnostic import affordable, buyable, target


class AffordabilityTests(unittest.TestCase):
    def test_gold_only_covers_remaining_deficit_and_bonuses_are_not_tokens(self):
        catalog = [('One', 0, 1, (3, 2, 0, 0, 0))]
        p = {'bonuses': [1, 0, 0, 0, 0], 'tokens': dict(white=1, blue=0, green=4, red=0, black=0, gold=2)}
        self.assertFalse(affordable(0, p, catalog))
        p['tokens']['gold'] = 3
        self.assertTrue(affordable(0, p, catalog))

    def test_own_hidden_reserve_is_visible_but_opponent_reserve_is_not_used(self):
        catalog = [('One', 0, 1, (0, 0, 0, 0, 0)), ('One', 0, 2, (0, 0, 0, 0, 0))]
        obs = {'public': {'market': [[None], [0], []], 'players': [
            {'bonuses': [0]*5, 'tokens': {c: 0 for c in ['white','blue','green','red','black','gold']}}]},
            'private': {'reserved': [{'slot': 2, 'card': 1, 'from_deck': True}]}}
        self.assertEqual(set(buyable(obs, 0, catalog)), {0, 1})
        self.assertEqual(target(obs, {'type': 'buy_reserved', 'slot': 2}), 1)
        self.assertEqual(target(obs, {'type': 'buy_market', 'tier': 'Two', 'slot': 0}), 0)


if __name__ == '__main__': unittest.main()
