//! Prism-only CLI: live agent, verified streaming extraction and parity probes.
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use splendor_agent::{run_agent, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{
    observation_hash, visible_events, Action, Audience, FullState, GameConfig, Ruleset,
};
use splendor_prism::{
    catalog_fingerprint, encode, EncodedState, PrismWeights, ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM,
    OBS_SCHEMA,
};
use splendor_replay::{verify_replay_trace, ReplayV1};

#[path = "prism_audit.rs"]
mod audit;

fn hash_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut buf = vec![0; 1024 * 1024];
    loop {
        let n = file.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
    }
    Ok(hex::encode(hash.finalize()))
}
fn options(args: &[String], allowed: &[&str]) -> Result<BTreeMap<String, String>, String> {
    if args.len() % 2 != 0 {
        return Err("every option requires a value".into());
    }
    let mut out = BTreeMap::new();
    for pair in args.chunks(2) {
        if !allowed.contains(&pair[0].as_str())
            || out.insert(pair[0].clone(), pair[1].clone()).is_some()
        {
            return Err(format!("unknown or repeated option {}", pair[0]));
        }
    }
    Ok(out)
}
fn required<'a>(opts: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str, String> {
    opts.get(key)
        .map(String::as_str)
        .ok_or_else(|| format!("missing {key}"))
}
fn new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    Ok(BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|e| format!("{}: {e}", path.display()))?,
    ))
}
fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let mut out = new_writer(path)?;
    serde_json::to_writer_pretty(&mut out, value).map_err(|e| e.to_string())?;
    writeln!(out).map_err(|e| e.to_string())?;
    out.flush().map_err(|e| e.to_string())
}
fn softmax(logits: &[f32]) -> Result<Vec<f32>, String> {
    if logits.is_empty() || logits.iter().any(|x| !x.is_finite()) {
        return Err("invalid policy logits".into());
    }
    let max = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let exp: Vec<f32> = logits.iter().map(|x| (x - max).exp()).collect();
    let sum: f32 = exp.iter().sum();
    Ok(exp.iter().map(|v| v / sum).collect())
}
fn best_action(logits: &[f32], legal: &[Action]) -> Result<usize, String> {
    if logits.len() != legal.len() || logits.is_empty() || logits.iter().any(|v| !v.is_finite()) {
        return Err("prediction/legal actions mismatch".into());
    }
    let mut best = 0;
    for i in 1..logits.len() {
        if logits[i] > logits[best]
            || (logits[i] == logits[best]
                && serde_json::to_string(&legal[i]).unwrap()
                    < serde_json::to_string(&legal[best]).unwrap())
        {
            best = i;
        }
    }
    Ok(best)
}
struct PrismPolicy {
    weights: PrismWeights,
    weights_sha256: String,
    decisions: Option<BufWriter<File>>,
}
impl AgentPolicy for PrismPolicy {
    type Error = String;
    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, String> {
        let start = Instant::now();
        let input = encode(
            &context.observation,
            context.visible_history,
            context.legal_actions,
        )?;
        let inference_start = Instant::now();
        let prediction = self.weights.predict(&input)?;
        let inference_us = inference_start.elapsed().as_secs_f64() * 1e6;
        let index = best_action(&prediction.logits, context.legal_actions)?;
        let decision_us = start.elapsed().as_secs_f64() * 1e6;
        if let Some(log) = &mut self.decisions {
            let bytes = serde_json::to_vec(&input).map_err(|e| e.to_string())?;
            let row = json!({"format":"prism-decision-v1", "model":"prism-v0.1",
                "weights_sha256":self.weights_sha256, "observation_schema":OBS_SCHEMA,"action_schema":ACTION_SCHEMA,
                "game_id":context.meta.game_id,"request_id":context.meta.request_id,
                "actor":context.observation.viewer,"observation_hash":context.meta.observation_hash,
                "observation":context.observation,"encoded_sha256":hex::encode(Sha256::digest(bytes)),
                "legal_actions":context.legal_actions,"logits":prediction.logits,
                "probabilities":softmax(&prediction.logits)?,"value":prediction.value,
                "selection":"greedy-semantic-tie-break","chosen_index":index,"chosen_action":context.legal_actions[index],
                "inference_us":inference_us,"decision_us":decision_us});
            serde_json::to_writer(&mut *log, &row).map_err(|e| e.to_string())?;
            writeln!(log).map_err(|e| e.to_string())?;
            log.flush().map_err(|e| e.to_string())?;
        }
        Ok(context.legal_actions[index])
    }
}
fn agent(args: &[String]) -> Result<(), String> {
    let opts = options(args, &["--weights", "--seed", "--decisions-out"])?;
    let path = Path::new(required(&opts, "--weights")?);
    let weights = PrismWeights::load(path)?;
    let weights_sha256 = hash_file(path)?;
    let seed = opts
        .get("--seed")
        .map(|s| s.parse::<u64>())
        .transpose()
        .map_err(|e| e.to_string())?
        .unwrap_or(51000001);
    let decisions = opts
        .get("--decisions-out")
        .map(|p| new_writer(Path::new(p)))
        .transpose()?;
    let policy = PrismPolicy {
        weights,
        weights_sha256,
        decisions,
    };
    run_agent(
        BufReader::new(io::stdin().lock()),
        io::stdout().lock(),
        io::stderr().lock(),
        AgentIdentity {
            name: "prism-v0.1",
            version: "0.1.0",
        },
        seed,
        policy,
    )
    .map_err(|e| e.to_string())
}
fn predict(args: &[String]) -> Result<(), String> {
    let opts = options(args, &["--weights", "--input", "--output"])?;
    let weights = PrismWeights::load(Path::new(required(&opts, "--weights")?))?;
    let reader =
        BufReader::new(File::open(required(&opts, "--input")?).map_err(|e| e.to_string())?);
    let mut writer = new_writer(Path::new(required(&opts, "--output")?))?;
    for line in reader.lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.len() > 64 * 1024 * 1024 {
            return Err("parity input row too large".into());
        }
        let row: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        let input: EncodedState = serde_json::from_value(row.get("input").unwrap_or(&row).clone())
            .map_err(|e| e.to_string())?;
        let prediction = weights.predict(&input)?;
        serde_json::to_writer(&mut writer, &prediction).map_err(|e| e.to_string())?;
        writeln!(writer).map_err(|e| e.to_string())?;
    }
    writer.flush().map_err(|e| e.to_string())
}
struct SplitWriter {
    path: PathBuf,
    files: BTreeMap<&'static str, BufWriter<File>>,
    states: u64,
    entities: u64,
    actions: u64,
    games: u64,
}
impl SplitWriter {
    fn new(path: PathBuf) -> Result<Self, String> {
        fs::create_dir(&path).map_err(|e| e.to_string())?;
        let mut files = BTreeMap::new();
        for name in [
            "entities.f32",
            "entity_offsets.u64",
            "actions.f32",
            "action_offsets.u64",
            "targets.i32",
            "chosen.u32",
            "outcomes.f32",
            "rows.jsonl",
        ] {
            files.insert(name, new_writer(&path.join(name))?);
        }
        files
            .get_mut("entity_offsets.u64")
            .unwrap()
            .write_all(&0u64.to_le_bytes())
            .map_err(|e| e.to_string())?;
        files
            .get_mut("action_offsets.u64")
            .unwrap()
            .write_all(&0u64.to_le_bytes())
            .map_err(|e| e.to_string())?;
        Ok(Self {
            path,
            files,
            states: 0,
            entities: 0,
            actions: 0,
            games: 0,
        })
    }
    fn add(
        &mut self,
        input: &EncodedState,
        chosen: usize,
        outcome: f32,
        row: Value,
    ) -> Result<(), String> {
        input.validate()?;
        if chosen >= input.actions.len() {
            return Err("invalid chosen index".into());
        }
        for (name, rows) in [
            ("entities.f32", &input.entities),
            ("actions.f32", &input.actions),
        ] {
            let out = self.files.get_mut(name).unwrap();
            for x in rows.iter().flatten() {
                out.write_all(&x.to_le_bytes()).map_err(|e| e.to_string())?;
            }
        }
        for t in &input.targets {
            self.files
                .get_mut("targets.i32")
                .unwrap()
                .write_all(&t.to_le_bytes())
                .map_err(|e| e.to_string())?;
        }
        self.entities += input.entities.len() as u64;
        self.actions += input.actions.len() as u64;
        self.states += 1;
        for (name, n) in [
            ("entity_offsets.u64", self.entities),
            ("action_offsets.u64", self.actions),
        ] {
            self.files
                .get_mut(name)
                .unwrap()
                .write_all(&n.to_le_bytes())
                .map_err(|e| e.to_string())?;
        }
        self.files
            .get_mut("chosen.u32")
            .unwrap()
            .write_all(&(chosen as u32).to_le_bytes())
            .map_err(|e| e.to_string())?;
        self.files
            .get_mut("outcomes.f32")
            .unwrap()
            .write_all(&outcome.to_le_bytes())
            .map_err(|e| e.to_string())?;
        let rows = self.files.get_mut("rows.jsonl").unwrap();
        serde_json::to_writer(&mut *rows, &row).map_err(|e| e.to_string())?;
        writeln!(rows).map_err(|e| e.to_string())?;
        Ok(())
    }
    fn finish(mut self) -> Result<Value, String> {
        let mut hashes = BTreeMap::new();
        for (name, writer) in &mut self.files {
            writer.flush().map_err(|e| e.to_string())?;
            hashes.insert(*name, hash_file(&self.path.join(name))?);
        }
        Ok(
            json!({"games":self.games,"states":self.states,"entities":self.entities,"actions":self.actions,"hashes":hashes}),
        )
    }
}
fn extract(args: &[String]) -> Result<(), String> {
    let opts = options(args, &["--manifest", "--out-dir"])?;
    let manifest_path = Path::new(required(&opts, "--manifest")?);
    let source: Value =
        serde_json::from_slice(&fs::read(manifest_path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    if source["stage"] != "collect" {
        return Err("only a training collection manifest is accepted".into());
    }
    let rows = source["rows"].as_array().ok_or("manifest missing rows")?;
    if rows.is_empty() {
        return Err("empty collection".into());
    }
    let out = Path::new(required(&opts, "--out-dir")?);
    fs::create_dir(out).map_err(|e| format!("output must be new: {e}"))?;
    let mut train = SplitWriter::new(out.join("train"))?;
    let mut val = SplitWriter::new(out.join("val"))?;
    let mut parity = new_writer(&out.join("parity.jsonl"))?;
    let mut parity_count = 0;
    let mut sources = Vec::new();
    let mut seeds = BTreeSet::new();
    let base = manifest_path.parent().ok_or("manifest parent missing")?;
    for (idx, row) in rows.iter().enumerate() {
        let path = base.join(row["replay_path"].as_str().ok_or("replay_path missing")?);
        let digest = hash_file(&path)?;
        if row["hashes"]["match-replay.json"] != digest {
            return Err(format!("replay hash mismatch {}", path.display()));
        }
        let replay: ReplayV1 = serde_json::from_slice(&fs::read(&path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        if replay.player_count != 2 || !seeds.insert(replay.seed) || row["seed"] != replay.seed {
            return Err("non-two-player/duplicate/wrong seed".into());
        }
        let trace = verify_replay_trace(&replay).map_err(|e| e.to_string())?;
        let is_val = replay.seed % 5 == 0;
        let split = if is_val { &mut val } else { &mut train };
        split.games += 1;
        for step in &trace.positions {
            let actor = step.recorded_actor;
            let obs = step.state.observation(actor);
            let legal = step.state.legal_actions();
            let history = visible_events(&step.state.log, Audience::Player(actor));
            let input = encode(&obs, &history, &legal)?;
            let chosen = legal
                .iter()
                .position(|a| *a == step.recorded_action)
                .ok_or("recorded action not legal")?;
            let outcome = if replay.result.winners.contains(&actor.0) {
                if replay.result.winners.len() == 1 {
                    1.0
                } else {
                    0.5
                }
            } else {
                0.0
            };
            split.add(
                &input,
                chosen,
                outcome,
                json!({"seed":replay.seed,"ply":step.ply,"actor":actor,
                "observation_hash":observation_hash(&obs),"chosen_action":step.recorded_action}),
            )?;
            // One varied decision from each of the first32 validation games, deterministic before training.
            if is_val && parity_count < 32 && step.ply as usize == (idx % 20) {
                serde_json::to_writer(
                    &mut parity,
                    &json!({"input":input,"seed":replay.seed,"ply":step.ply,"actor":actor}),
                )
                .map_err(|e| e.to_string())?;
                writeln!(parity).map_err(|e| e.to_string())?;
                parity_count += 1;
            }
        }
        sources.push(json!({"seed":replay.seed,"path":path,"sha256":digest,"split":if is_val{"val"}else{"train"},"steps":trace.positions.len()}));
        if (idx + 1) % 100 == 0 {
            println!("extracted {}/{} games", idx + 1, rows.len());
        }
    }
    parity.flush().map_err(|e| e.to_string())?;
    let manifest = json!({"format":"prism-dataset-v1","observation_schema":OBS_SCHEMA,"action_schema":ACTION_SCHEMA,
        "catalog_fingerprint":catalog_fingerprint(),"entity_dim":ENTITY_DIM,"action_dim":ACTION_DIM,
        "source_manifest_sha256":hash_file(manifest_path)?,"sources":sources,"parity_states":parity_count,
        "splits":{"train":train.finish()?,"val":val.finish()?}});
    write_json(&out.join("manifest.json"), &manifest)?;
    println!("Prism dataset complete: {}", out.display());
    Ok(())
}
fn fixtures(args: &[String]) -> Result<(), String> {
    let opts = options(args, &["--output"])?;
    let mut out = new_writer(Path::new(required(&opts, "--output")?))?;
    // Deterministic engineering fixtures, not competitive measurements.
    let (mut state, _) = FullState::new(GameConfig {
        player_count: 2,
        seed: 51012345,
        ruleset: Ruleset::base_v1(),
    })
    .map_err(|e| e.to_string())?;
    for n in 0..64usize {
        let legal = state.legal_actions();
        if legal.is_empty() {
            break;
        }
        let actor = state.current_player;
        let input = encode(
            &state.observation(actor),
            &visible_events(&state.log, Audience::Player(actor)),
            &legal,
        )?;
        serde_json::to_writer(&mut out, &json!({"input":input,"fixture":n}))
            .map_err(|e| e.to_string())?;
        writeln!(out).map_err(|e| e.to_string())?;
        let pick = (n * 17 + 3) % legal.len();
        state.apply(legal[pick]).map_err(|e| e.to_string())?;
    }
    // Explicit synthetic boundary roots: all seven action kinds, high action counts,
    // own blind reserve, multiple nobles, exhausted board and final-round masks.
    let (mut s, _) = FullState::new(GameConfig {
        seed: 51012345,
        ..Default::default()
    })
    .map_err(|e| e.to_string())?;
    s.apply(Action::ReserveDeck {
        tier: splendor_catalog::Tier::ALL[0],
        give_back: splendor_core::Gems::ZERO,
    })
    .map_err(|e| e.to_string())?;
    s.apply(s.legal_actions()[0]).map_err(|e| e.to_string())?;
    s.players[0].bonuses = [4; 5];
    let mut roots = vec![s.clone()];
    s.phase = splendor_core::Phase::ChooseNoble;
    s.pending_nobles = s.nobles.clone();
    roots.push(s.clone());
    s.phase = splendor_core::Phase::Main;
    s.pending_nobles.clear();
    s.market = [[None; 4]; 3];
    s.decks = [vec![], vec![], vec![]];
    s.players[0].reserved.clear();
    s.bank = splendor_core::Gems::ZERO;
    roots.push(s);
    let (mut s, _) = FullState::new(GameConfig {
        seed: 51012345,
        ..Default::default()
    })
    .map_err(|e| e.to_string())?;
    s.players[0].tokens = splendor_core::Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    };
    s.bank = splendor_core::Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 5,
    };
    s.end_game_triggered = true;
    s.turns_remaining_in_final_round = Some(0);
    roots.push(s);
    for (index, s) in roots.iter().enumerate() {
        let input = encode(
            &s.observation(s.current_player),
            &visible_events(&s.log, Audience::Player(s.current_player)),
            &s.legal_actions(),
        )?;
        serde_json::to_writer(&mut out, &json!({"input":input,"boundary_fixture":index}))
            .map_err(|e| e.to_string())?;
        writeln!(out).map_err(|e| e.to_string())?;
    }
    out.flush().map_err(|e| e.to_string())
}
pub fn run(command: &str, args: &[String]) -> i32 {
    let result = match command {
        "agent-prism" => agent(args),
        "prism-extract" => extract(args),
        "prism-predict" => predict(args),
        "prism-fixtures" => fixtures(args),
        "prism-audit" => audit::run(args),
        _ => Err("unknown Prism command".into()),
    };
    match result {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("Prism error: {e}");
            1
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unknown_duplicate_missing_options() {
        assert!(options(&["--oops".into(), "1".into()], &["--weights"]).is_err());
        assert!(options(&["--weights".into()], &["--weights"]).is_err());
        assert!(options(
            &[
                "--weights".into(),
                "x".into(),
                "--weights".into(),
                "y".into()
            ],
            &["--weights"]
        )
        .is_err());
        assert!(agent(&[]).is_err());
    }
    #[test]
    fn softmax_and_fail_closed_selection() {
        let p = softmax(&[1000.0, 1000.0]).unwrap();
        assert_eq!(p, vec![0.5, 0.5]);
        assert!(softmax(&[f32::NAN]).is_err());
        assert!(best_action(&[], &[]).is_err());
        assert!(best_action(&[f32::INFINITY], &[Action::Pass]).is_err());
    }
    #[test]
    fn encoding_live_equals_verified_replay_projection() {
        use splendor_replay::ReplayRecorder;
        let mut recorder = ReplayRecorder::new(GameConfig {
            player_count: 2,
            seed: 17,
            ruleset: Ruleset::base_v1(),
        })
        .unwrap();
        let mut live = Vec::new();
        let mut transcript = visible_events(
            &recorder.state().log,
            Audience::Player(splendor_core::PlayerId(0)),
        );
        for n in 0..1000usize {
            if recorder.is_terminal() {
                break;
            }
            let state = recorder.state();
            let actor = state.current_player;
            let legal = state.legal_actions();
            // A transport round-trip, using incremental visible events, not the offline log projection.
            if actor.0 == 0 {
                let obs = serde_json::from_str(
                    &serde_json::to_string(&state.observation(actor)).unwrap(),
                )
                .unwrap();
                live.push(encode(&obs, &transcript, &legal).unwrap());
            }
            let buys: Vec<_> = legal
                .iter()
                .copied()
                .filter(|a| {
                    matches!(
                        a,
                        Action::BuyMarket { .. }
                            | Action::BuyReserved { .. }
                            | Action::ChooseNoble { .. }
                    )
                })
                .collect();
            let action = if buys.is_empty() {
                legal[(n * 17 + 3) % legal.len()]
            } else {
                buys[n % buys.len()]
            };
            let result = recorder.apply(action).unwrap();
            transcript.extend(visible_events(
                &result.events,
                Audience::Player(splendor_core::PlayerId(0)),
            ));
        }
        assert!(recorder.is_terminal());
        let (_, replay) = recorder.finish().unwrap();
        let trace = verify_replay_trace(&replay).unwrap();
        let offline: Vec<_> = trace
            .positions
            .iter()
            .filter(|p| p.recorded_actor.0 == 0)
            .map(|p| {
                encode(
                    &p.state.observation(p.recorded_actor),
                    &visible_events(&p.state.log, Audience::Player(p.recorded_actor)),
                    &p.state.legal_actions(),
                )
                .unwrap()
            })
            .collect();
        assert!(live.len() > 20);
        assert_eq!(live, offline);
    }
}
