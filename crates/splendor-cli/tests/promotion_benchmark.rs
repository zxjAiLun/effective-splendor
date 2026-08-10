//! Frozen-input contract for the M09 competitive calibration run.

use splendor_eval::{
    evaluation_plan_hash_v1, expand_schedule, promotion_gate_hash_v1, EvaluationPlanV1,
    PromotionGateV1,
};

const PLAN_JSON: &str = include_str!("../../../benchmarks/m09-competitive-eval-v1.plan.json");
const GATE_JSON: &str = include_str!("../../../benchmarks/m09-competitive-eval-v1.gate.json");
const PLAN_HASH: &str = "95b3c89c56f6411b6ce697ae7e15980ef3089045d33df826780d5c44590a26f5";
const GATE_HASH: &str = "8224cfc0e3022f20334b40483e458854c5bccfcb3ca0c48200cc35586c86efdb";

#[test]
fn m09_calibration_inputs_are_valid_and_frozen() {
    let plan: EvaluationPlanV1 = serde_json::from_str(PLAN_JSON).unwrap();
    let gate: PromotionGateV1 = serde_json::from_str(GATE_JSON).unwrap();

    plan.validate().unwrap();
    gate.validate().unwrap();
    assert_eq!(plan.game_seeds.len(), 32);
    assert_eq!(expand_schedule(&plan).unwrap().len(), 64);
    assert_eq!(gate.min_completed_seed_blocks, 32);
    assert_eq!(gate.candidate_agent_id, plan.agents[0].id);
    assert_eq!(gate.champion_agent_id, plan.agents[1].id);
    assert_eq!(evaluation_plan_hash_v1(&plan).unwrap().as_str(), PLAN_HASH);
    assert_eq!(promotion_gate_hash_v1(&gate).unwrap().as_str(), GATE_HASH);
}
