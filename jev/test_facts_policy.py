"""Facts-only policy mappings, masks and overflow; no paid calls."""
import copy
import itertools
import json
import unittest
from pathlib import Path

import agent
from test_agent import answer

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = [json.loads(x) for x in (ROOT / "fixtures/protocol/v0.5/normal-game.ndjson").read_text().splitlines()]
OBS = next(x["observation"] for x in MESSAGES if x["type"] == "observation")
LEGAL = next(x["legal_actions"] for x in MESSAGES if x["type"] == "request_action")
CAT = agent.load_catalog()


def probs(*values):
    return dict(zip(agent.COLORS, values or [.2] * 5))


def take(**kw):
    return {"type": "take_tokens", "take": agent.gems(kw), "return": agent.gems({})}


class FactsPolicyTests(unittest.TestCase):
    def pick(self, legal, choices=None, probabilities=None, obs=None):
        self.payloads, self.traces = [], []
        choices = choices or {}
        def fake(payload):
            self.payloads.append(payload)
            stage, q = next(iter(payload["questions"].items()))
            p = probabilities if probabilities is not None else probs()
            selected = choices.get(stage, max(p, key=p.get) if stage == "colors" else next(iter(q["criteria"])))
            return answer(stage, selected, p if stage == "colors" else None)
        result = agent.pick(obs or OBS, legal, CAT, fake, lambda **kw: self.traces.append(kw))
        self.assertIn(result[0], legal)
        self.assertEqual(legal[self.traces[0]["selected_index"]], result[0])
        self.assertEqual(self.traces[0]["cap_removed"], 0)
        return result[0]

    def test_distinct_uses_top_three_not_choice_alone(self):
        selected = self.pick(LEGAL, {"family": "take_distinct"}, probs(.05, .3, .2, .4, .05))
        self.assertEqual(agent.sparse_gems(selected["take"]), {"blue": 1, "green": 1, "red": 1})
        self.assertEqual([next(iter(p["questions"])) for p in self.payloads], ["family", "colors"])
        mapped = next(p for p in self.traces[0]["selection_path"] if p["stage"] == "colors")
        self.assertEqual(mapped["ranked_eligible_colors"][:3], ["red", "blue", "green"])

    def test_double_uses_highest_eligible_probability(self):
        obs = copy.deepcopy(OBS)
        obs["public"]["bank"].update(white=3, green=0, black=2)
        selected = self.pick([take(blue=2), take(red=2)], probabilities=probs(.7, .05, .01, .2, .04), obs=obs)
        self.assertEqual(agent.sparse_gems(selected["take"]), {"red": 2})
        criteria = self.payloads[0]["questions"]["colors"]["criteria"]
        self.assertEqual(len(criteria), 5)
        self.assertFalse(criteria["white"]["eligible"])
        self.assertEqual(criteria["white"]["bank_count"], 3)
        self.assertTrue(criteria["red"]["eligible"])

    def test_ties_have_frozen_color_order_not_return_tiebreak(self):
        selected = self.pick(LEGAL, {"family": "take_distinct"}, probs())
        self.assertEqual(agent.sparse_gems(selected["take"]), {"white": 1, "blue": 1, "green": 1})
        selected = self.pick(LEGAL, {"family": "take_double"}, probs())
        self.assertEqual(agent.sparse_gems(selected["take"]), {"white": 2})

    def test_depleted_colors_masked_from_distinct_top_k(self):
        obs = copy.deepcopy(OBS)
        obs["public"]["bank"]["white"] = 0
        legal = [take(**dict.fromkeys(cs, 1)) for cs in itertools.combinations(agent.COLORS[1:], 3)]
        selected = self.pick(legal, probabilities=probs(.7, .03, .1, .12, .05), obs=obs)
        self.assertEqual(agent.sparse_gems(selected["take"]), {"green": 1, "red": 1, "black": 1})

    def test_fewer_than_three_colors_and_forced_double_no_call(self):
        for legal in ([take(white=1, red=1)], [take(blue=1)], [take(black=2)]):
            self.assertEqual(self.pick(legal), legal[0])
            self.assertEqual(self.payloads, [])

    def test_gold_is_never_a_take_choice(self):
        self.pick(LEGAL, {"family": "take_double"})
        self.assertNotIn("gold", self.payloads[1]["questions"]["colors"]["criteria"])
        with self.assertRaises(agent.AgentFault):
            self.pick([take(gold=1)])

    def test_invalid_probability_vectors_fail_closed(self):
        bads = [None, {}, probs(.3, .3, .3, .3, .3), probs(-.1, .3, .3, .3, .2),
                probs(float("nan"), .2, .2, .2, .2), probs(float("inf"), 0, 0, 0, 0),
                probs(True, 0, 0, 0, 0), probs("0.2", .2, .2, .2, .2), dict(probs(), gold=0)]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(agent.AgentFault) as exc:
                agent.pick(OBS, [take(white=2), take(blue=2)], CAT,
                           lambda _: answer("colors", "white", bad))
            self.assertEqual(exc.exception.code, "invalid_probabilities")

    def test_unmappable_top_k_fails_instead_of_nearest_action(self):
        # An inconsistent certified set must not trigger an invented fallback.
        with self.assertRaises(agent.AgentFault) as exc:
            self.pick([take(white=1, blue=1, green=1), take(white=1, red=1, black=1)],
                      probabilities=probs(.3, .25, .05, .35, .05))
        self.assertEqual(exc.exception.code, "unmappable_colors")

    def test_buy_mask_and_reserved_purchase(self):
        obs = copy.deepcopy(OBS)
        obs["private"]["reserved"] = [{"slot": 0, "card": 15}]
        legal = [take(white=2), {"type": "buy_market", "tier": "One", "slot": 0},
                 {"type": "buy_reserved", "slot": 0}]
        selected = self.pick(legal, {"family": "buy", "target": "t1"}, obs=obs)
        self.assertEqual(selected, legal[2])
        criteria = self.payloads[1]["questions"]["target"]["criteria"]
        self.assertEqual(len(criteria), 2)  # No unaffordable card is fabricated.
        self.assertEqual(criteria["t1"]["card_id"], 15)
        self.assertEqual(self.payloads[1]["state"]["own_reserved"][0]["card"]["id"], 15)

    def test_reserve_targets_group_returns_without_removing_variants(self):
        obs = copy.deepcopy(OBS)
        obs["public"]["players"][0]["tokens"] = agent.gems({"white": 3, "blue": 3, "green": 3, "gold": 1})
        legal = []
        for action in ({"type": "reserve_market", "tier": "One", "slot": 0},
                       {"type": "reserve_deck", "tier": "Two"}):
            for color in ("white", "blue", "green", "gold"):
                legal.append(dict(action, **{"return": agent.gems({color: 1})}))
        selected = self.pick(legal, {"target": "t1", "return": "r3"}, obs=obs)
        self.assertEqual(selected, legal[7])
        self.assertEqual(self.traces[0]["offered_indices"], [4, 5, 6, 7])
        stages = [next(iter(p["questions"])) for p in self.payloads]
        self.assertEqual(stages, ["target", "return"])
        self.assertEqual(len(self.payloads[0]["questions"]["target"]["criteria"]), 2)
        self.assertEqual(len(self.payloads[1]["questions"]["return"]["criteria"]), 4)
        progress = self.payloads[1]["state"]["action_in_progress"]
        self.assertEqual(progress["received_before_returns"], {"gold": 1})
        self.assertEqual(progress["tokens_before_returns"]["gold"], 2)
        self.assertTrue(progress["target"]["unknown_card"])

    def test_take_overflow_return_is_explicit_and_noop_not_deleted(self):
        legal = [dict(take(white=2), **{"return": agent.gems({c: 2})}) for c in ("white", "blue")]
        self.assertEqual(self.pick(legal, {"return": "r0"}), legal[0])
        self.assertEqual([next(iter(p["questions"])) for p in self.payloads], ["return"])
        self.assertEqual(self.traces[0]["noops_removed"], 0)
        self.assertEqual(len(self.payloads[0]["questions"]["return"]["criteria"]), 2)

    def test_reserve_cap_empty_decks_and_no_gold_follow_certified_set(self):
        obs = copy.deepcopy(OBS)
        obs["public"]["players"][0]["reserved_count"] = 3
        obs["public"]["deck_counts"] = [0, 0, 0]
        obs["public"]["bank"]["gold"] = 0
        self.pick([take(white=2), take(blue=2)], obs=obs)
        self.assertNotIn("family", self.payloads[0]["questions"])
        legal = [{"type": "reserve_market", "tier": "One", "slot": i, "return": agent.gems({})} for i in (0, 1)]
        self.pick(legal, obs=obs)
        criteria = self.payloads[0]["questions"]["target"]["criteria"]
        self.assertTrue(all(v["type"] == "reserve_market" for v in criteria.values()))
        self.assertEqual(self.payloads[0]["state"]["bank"]["gold"], 0)

    def test_noble_and_pass(self):
        nobles = [{"type": "choose_noble", "noble": i} for i in (0, 1)]
        self.assertEqual(self.pick(nobles, {"noble": "t1"}), nobles[1])
        self.assertEqual(list(self.payloads[0]["questions"]), ["noble"])
        self.assertEqual(self.pick([{"type": "pass"}]), {"type": "pass"})
        self.assertEqual(self.payloads, [])

    def test_provider_limit_is_not_a_heuristic_cap(self):
        with self.assertRaises(agent.AgentFault) as exc:
            agent.question({}, "return", "choose", {str(i): i for i in range(256)})
        self.assertEqual(exc.exception.code, "choice_count")


if __name__ == "__main__":
    unittest.main()
