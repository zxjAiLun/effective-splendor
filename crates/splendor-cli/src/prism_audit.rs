//! Referee-only audit; never reachable from the live policy input path.
use super::*;

pub(super) fn run(args: &[String]) -> Result<(), String> {
    let opts = options(args, &["--manifest", "--weights", "--output"])?;
    let manifest_path = Path::new(required(&opts, "--manifest")?);
    let manifest: Value =
        serde_json::from_slice(&fs::read(manifest_path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let base = manifest_path.parent().ok_or("manifest parent missing")?;
    let weight_path = Path::new(required(&opts, "--weights")?);
    let weights = PrismWeights::load(weight_path)?;
    let weight_sha = hash_file(weight_path)?;
    let rows = manifest["rows"].as_array().ok_or("missing match rows")?;
    let mut games = Vec::new();
    let mut total = 0usize;
    for row in rows {
        let path = base.join(row["replay_path"].as_str().ok_or("missing replay path")?);
        let dir = path.parent().ok_or("missing replay directory")?;
        if row["identity"]["weights_sha256"] != weight_sha {
            return Err("match model identity mismatch".into());
        }
        for (name, digest) in row["hashes"].as_object().ok_or("missing hashes")? {
            if hash_file(&dir.join(name))? != digest.as_str().ok_or("bad digest")? {
                return Err(format!(
                    "artifact hash mismatch: {}",
                    dir.join(name).display()
                ));
            }
        }
        let replay: ReplayV1 = serde_json::from_slice(&fs::read(&path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let trace = verify_replay_trace(&replay).map_err(|e| e.to_string())?;
        let report: Value = serde_json::from_slice(
            &fs::read(dir.join("arena-report.json")).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        let result = serde_json::to_value(&replay.result).map_err(|e| e.to_string())?;
        if report["outcome"]["status"] != "completed"
            || report["outcome"]["result"] != result
            || row["result"] != result
            || row["seed"] != replay.seed
            || row["plies"] != trace.positions.len()
        {
            return Err("report/replay result mismatch".into());
        }
        let seat = row["candidate_seat"]
            .as_u64()
            .filter(|s| *s < 2)
            .ok_or("bad candidate seat")? as u8;
        let mut decisions =
            BufReader::new(File::open(dir.join("decisions.jsonl")).map_err(|e| e.to_string())?)
                .lines();
        let mut ids = BTreeSet::new();
        let mut main = [0usize; 2];
        let mut noble = [0usize; 2];
        for step in &trace.positions {
            if step.recorded_action.is_main_action() {
                main[step.recorded_actor.index()] += 1;
            } else {
                noble[step.recorded_actor.index()] += 1;
            }
            if step.recorded_actor.0 != seat {
                continue;
            }
            let line = decisions
                .next()
                .ok_or("missing decision")?
                .map_err(|e| e.to_string())?;
            let decision: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
            let id = decision["request_id"]
                .as_u64()
                .ok_or("missing request_id")?;
            if !ids.insert(id) {
                return Err("duplicate decision request".into());
            }
            let obs = step.state.observation(step.recorded_actor);
            let legal = step.state.legal_actions();
            let history = visible_events(&step.state.log, Audience::Player(step.recorded_actor));
            let input = encode(&obs, &history, &legal)?;
            let input_sha = hex::encode(Sha256::digest(
                serde_json::to_vec(&input).map_err(|e| e.to_string())?,
            ));
            let obs_json = serde_json::to_value(&obs).map_err(|e| e.to_string())?;
            if decision["format"] != "prism-decision-v1"
                || decision["model"] != "prism-v0.1"
                || decision["weights_sha256"] != weight_sha
                || decision["observation_schema"] != OBS_SCHEMA
                || decision["action_schema"] != ACTION_SCHEMA
                || decision["game_id"] != report["game_id"]
                || decision["actor"] != seat
                || decision["observation"] != obs_json
                || decision["observation_hash"] != json!(observation_hash(&obs))
                || decision["encoded_sha256"] != input_sha
                || decision["legal_actions"] != json!(legal)
            {
                return Err(format!(
                    "decision identity/input mismatch seed{} ply{}",
                    replay.seed, step.ply
                ));
            }
            let prediction = weights.predict(&input)?;
            let chosen = best_action(&prediction.logits, &legal)?;
            if decision["chosen_index"] != chosen
                || decision["chosen_action"] != json!(legal[chosen])
                || legal[chosen] != step.recorded_action
                || decision["selection"] != "greedy-semantic-tie-break"
            {
                return Err("decision/replay selection mismatch".into());
            }
            for (key, expected) in [
                ("logits", prediction.logits.clone()),
                ("probabilities", softmax(&prediction.logits)?),
            ] {
                let actual: Vec<f32> =
                    serde_json::from_value(decision[key].clone()).map_err(|e| e.to_string())?;
                if actual.len() != expected.len()
                    || actual
                        .iter()
                        .zip(expected)
                        .any(|(a, b)| !a.is_finite() || (*a - b).abs() > 1e-5)
                {
                    return Err(format!("decision {key} differs from model"));
                }
            }
            let value = decision["value"].as_f64().ok_or("bad value")?;
            if !value.is_finite() || (value - prediction.value as f64).abs() > 1e-6 {
                return Err("decision value mismatch".into());
            }
            for key in ["inference_us", "decision_us"] {
                if !decision[key]
                    .as_f64()
                    .is_some_and(|v| v.is_finite() && v >= 0.0)
                {
                    return Err("invalid latency".into());
                }
            }
            total += 1;
        }
        if decisions.next().is_some() {
            return Err("extra decision rows".into());
        }
        let last = trace.positions.last().ok_or("empty replay")?;
        let mut final_state = last.state.clone();
        final_state
            .apply(last.recorded_action)
            .map_err(|e| e.to_string())?;
        games.push(json!({"seed":replay.seed,"candidate_seat":seat,"decision_rows":ids.len(),"main_actions":main,"choose_noble_actions":noble,"result":replay.result,"final_public":final_state.observation(splendor_core::PlayerId(0)).public}));
    }
    write_json(
        Path::new(required(&opts, "--output")?),
        &json!({"format":"prism-decision-audit-v1","status":"PASS","games":games,"verified_decisions":total,"manifest_sha256":hash_file(manifest_path)?,"weights_sha256":weight_sha,"illegal_actions":0,"fallbacks":0,"truncations":0,"decision_mismatches":0}),
    )?;
    println!("Prism audit PASS games={} decisions={total}", rows.len());
    Ok(())
}
