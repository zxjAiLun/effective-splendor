//! Isolated M54 Stage I sampling and replay-audit commands for Prism PPO.
//!
//! This module does not change the existing Prism policy, weights, or default
//! agent. The learner is a local loopback service and only receives M51's
//! player-view encoding.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::net::{Shutdown, SocketAddr, SocketAddrV4, TcpStream};
use std::path::Path;
use std::str::FromStr;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use splendor_agent::{run_agent, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{
    visible_events, Action, Audience, GameResult, Observation, PlayerId, VisibleEvent,
};
use splendor_prism::{catalog_fingerprint, encode, EncodedState};
use splendor_replay::{verify_replay_trace, ReplayV1, REPLAY_FORMAT, REPLAY_VERSION};

const REQUEST_FORMAT: &str = "prism-ppo-request-v1";
const RESPONSE_FORMAT: &str = "prism-ppo-response-v1";
const DECISION_FORMAT: &str = "prism-ppo-decision-v1";
const AUDIT_FORMAT: &str = "prism-ppo-audit-v1";
const MAX_MESSAGE_BYTES: usize = 16 * 1024 * 1024;
const MAX_REPLAY_BYTES: u64 = 256 * 1024 * 1024;
const MAX_SIDECAR_BYTES: u64 = 256 * 1024 * 1024;
const MAX_SIDECAR_ROWS: usize = 1_000_000;
const IO_TIMEOUT: Duration = Duration::from_secs(30);
const DEFAULT_SEED: u64 = 51_000_001;

/// Request identity and player-view features shared with the Python service.
/// The secret token is intentionally not part of this type, so it cannot enter
/// a decision sidecar by accident.
#[derive(Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct RequestBody {
    format: String,
    behavior_id: String,
    job_id: String,
    game_id: String,
    actor: u8,
    request_id: u64,
    decision_index: u64,
    catalog_fingerprint: String,
    input: EncodedState,
}

#[derive(Serialize)]
struct WireRequest<'a> {
    format: &'static str,
    token: &'a str,
    behavior_id: &'a str,
    job_id: &'a str,
    game_id: &'a str,
    actor: u8,
    request_id: u64,
    decision_index: u64,
    catalog_fingerprint: &'a str,
    input: &'a EncodedState,
}

#[derive(Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct PpoResponse {
    format: String,
    behavior_id: String,
    job_id: String,
    game_id: String,
    actor: u8,
    request_id: u64,
    decision_index: u64,
    chosen_index: usize,
    log_prob: f64,
    value: f64,
    style_value: f64,
    probabilities: Vec<f64>,
}

#[derive(Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct DecisionRow {
    format: String,
    request: RequestBody,
    response: PpoResponse,
    observation: Observation,
    visible_history: Vec<VisibleEvent>,
    legal_actions: Vec<Action>,
    chosen_action: Action,
}

fn options(args: &[String], allowed: &[&str]) -> Result<BTreeMap<String, String>, String> {
    if args.len() % 2 != 0 {
        return Err("every option requires a value".into());
    }
    let mut parsed = BTreeMap::new();
    for pair in args.chunks_exact(2) {
        if !allowed.contains(&pair[0].as_str()) || parsed.contains_key(&pair[0]) {
            return Err(format!("unknown or repeated option {}", pair[0]));
        }
        parsed.insert(pair[0].clone(), pair[1].clone());
    }
    Ok(parsed)
}

fn required<'a>(opts: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str, String> {
    opts.get(key)
        .map(String::as_str)
        .ok_or_else(|| format!("missing {key}"))
}

fn validate_behavior_id(value: &str) -> Result<(), String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("behavior-id must be 64 lowercase hexadecimal characters".into());
    }
    Ok(())
}

fn validate_text(value: &str, name: &str) -> Result<(), String> {
    if value.is_empty() || value.chars().count() > 256 || value.chars().any(|c| c < ' ') {
        return Err(format!("invalid {name}"));
    }
    Ok(())
}

fn validate_endpoint(value: &str) -> Result<SocketAddrV4, String> {
    let addr = SocketAddr::from_str(value)
        .map_err(|_| "endpoint must be a numeric 127.0.0.1:PORT address".to_string())?;
    match addr {
        SocketAddr::V4(v4) if v4.ip().octets() == [127, 0, 0, 1] && v4.port() != 0 => Ok(v4),
        _ => Err("endpoint must be a numeric 127.0.0.1:PORT address".into()),
    }
}

fn validate_response(
    response: &PpoResponse,
    request: &RequestBody,
    action_count: usize,
) -> Result<(), String> {
    if response.format != RESPONSE_FORMAT
        || response.behavior_id != request.behavior_id
        || response.job_id != request.job_id
        || response.game_id != request.game_id
        || response.actor != request.actor
        || response.request_id != request.request_id
        || response.decision_index != request.decision_index
    {
        return Err("learner response correlation mismatch".into());
    }
    if action_count == 0
        || response.chosen_index >= action_count
        || response.probabilities.len() != action_count
    {
        return Err("learner response action count/index mismatch".into());
    }
    if !response.log_prob.is_finite()
        || !response.value.is_finite()
        || !(0.0..=1.0).contains(&response.value)
        || !response.style_value.is_finite()
    {
        return Err("learner response contains invalid values".into());
    }
    if response
        .probabilities
        .iter()
        .any(|p| !p.is_finite() || !(0.0..=1.0).contains(p))
    {
        return Err("learner response probabilities are invalid".into());
    }
    let total: f64 = response.probabilities.iter().sum();
    if !total.is_finite() || (total - 1.0).abs() > 1e-10 {
        return Err("learner response probabilities are not normalized".into());
    }
    let selected = response.probabilities[response.chosen_index];
    if response.log_prob > 0.0 {
        return Err("learner log probability must be nonpositive".into());
    }
    if selected <= 0.0 || (selected.ln() - response.log_prob).abs() > 1e-10 {
        return Err("learner response log probability mismatch".into());
    }
    Ok(())
}

fn exchange(
    endpoint: SocketAddrV4,
    token: &str,
    body: &RequestBody,
) -> Result<PpoResponse, String> {
    let wire = WireRequest {
        format: REQUEST_FORMAT,
        token,
        behavior_id: &body.behavior_id,
        job_id: &body.job_id,
        game_id: &body.game_id,
        actor: body.actor,
        request_id: body.request_id,
        decision_index: body.decision_index,
        catalog_fingerprint: &body.catalog_fingerprint,
        input: &body.input,
    };
    let mut bytes = serde_json::to_vec(&wire).map_err(|_| "cannot serialize learner request")?;
    if bytes
        .len()
        .checked_add(1)
        .filter(|n| *n <= MAX_MESSAGE_BYTES)
        .is_none()
    {
        return Err("learner request exceeds the 16 MiB message limit".into());
    }
    bytes.push(b'\n');

    let mut stream = TcpStream::connect_timeout(&SocketAddr::V4(endpoint), IO_TIMEOUT)
        .map_err(|_| "cannot connect to configured loopback learner endpoint")?;
    stream
        .set_read_timeout(Some(IO_TIMEOUT))
        .and_then(|_| stream.set_write_timeout(Some(IO_TIMEOUT)))
        .map_err(|_| "cannot configure learner socket timeout")?;
    stream
        .write_all(&bytes)
        .and_then(|_| stream.flush())
        .map_err(|_| "failed writing learner request")?;
    stream
        .shutdown(Shutdown::Write)
        .map_err(|_| "failed to finish learner request")?;

    let mut response_bytes = Vec::new();
    stream
        .take((MAX_MESSAGE_BYTES + 1) as u64)
        .read_to_end(&mut response_bytes)
        .map_err(|_| "failed reading learner response")?;
    if response_bytes.len() > MAX_MESSAGE_BYTES {
        return Err("learner response exceeds the 16 MiB message limit".into());
    }
    if !response_bytes.ends_with(b"\n") {
        return Err("learner response must end in a newline".into());
    }
    let response: PpoResponse = serde_json::from_slice(&response_bytes)
        .map_err(|_| "learner returned an invalid response document")?;
    validate_response(&response, body, body.input.actions.len())?;
    Ok(response)
}

fn create_new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| "sidecar output must be a new writable file".to_string())?;
    Ok(BufWriter::new(file))
}

struct RemotePolicy {
    endpoint: SocketAddrV4,
    token: String,
    behavior_id: String,
    job_id: String,
    decision_index: u64,
    sidecar: BufWriter<File>,
}

impl AgentPolicy for RemotePolicy {
    type Error = String;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, String> {
        let actor = context.meta.recipient_seat;
        if context.meta.request_id == 0 {
            return Err("protocol request_id must be positive".into());
        }
        if context.observation.public.player_count != 2
            || context.observation.viewer != actor
            || context.observation.public.current_player != actor
            || actor.0 > 1
        {
            return Err("Prism PPO requires the current two-player recipient observation".into());
        }
        let input = encode(
            &context.observation,
            context.visible_history,
            context.legal_actions,
        )?;
        let body = RequestBody {
            format: REQUEST_FORMAT.to_string(),
            behavior_id: self.behavior_id.clone(),
            job_id: self.job_id.clone(),
            game_id: context.meta.game_id.clone(),
            actor: actor.0,
            request_id: context.meta.request_id,
            decision_index: self.decision_index,
            catalog_fingerprint: catalog_fingerprint(),
            input,
        };
        let response = exchange(self.endpoint, &self.token, &body)?;
        let chosen_action = *context
            .legal_actions
            .get(response.chosen_index)
            .ok_or_else(|| "learner selected an out-of-range action".to_string())?;
        let row = DecisionRow {
            format: DECISION_FORMAT.to_string(),
            request: body,
            response,
            observation: context.observation,
            visible_history: context.visible_history.to_vec(),
            legal_actions: context.legal_actions.to_vec(),
            chosen_action,
        };
        serde_json::to_writer(&mut self.sidecar, &row)
            .map_err(|_| "cannot serialize decision sidecar row".to_string())?;
        self.sidecar
            .write_all(b"\n")
            .map_err(|_| "cannot durably write decision sidecar row".to_string())?;
        self.sidecar
            .flush()
            .and_then(|_| self.sidecar.get_ref().sync_data())
            .map_err(|_| "cannot durably write decision sidecar row".to_string())?;
        self.decision_index = self
            .decision_index
            .checked_add(1)
            .ok_or_else(|| "decision index overflow".to_string())?;
        Ok(chosen_action)
    }
}

fn run_agent_command(args: &[String]) -> Result<(), String> {
    let opts = options(
        args,
        &[
            "--endpoint",
            "--token",
            "--behavior-id",
            "--job-id",
            "--seed",
            "--decisions-out",
        ],
    )?;
    let endpoint = validate_endpoint(required(&opts, "--endpoint")?)?;
    let token = required(&opts, "--token")?;
    validate_text(token, "token")?;
    let behavior_id = required(&opts, "--behavior-id")?.to_string();
    validate_behavior_id(&behavior_id)?;
    let job_id = required(&opts, "--job-id")?.to_string();
    validate_text(&job_id, "job-id")?;
    let output_path = Path::new(required(&opts, "--decisions-out")?);
    let seed = opts
        .get("--seed")
        .map(|s| {
            s.parse::<u64>()
                .map_err(|_| "seed must be an unsigned integer".to_string())
        })
        .transpose()?
        .unwrap_or(DEFAULT_SEED);
    let sidecar = create_new_writer(output_path)?;
    let policy = RemotePolicy {
        endpoint,
        token: token.to_string(),
        behavior_id,
        job_id,
        decision_index: 0,
        sidecar,
    };
    run_agent(
        BufReader::new(io::stdin().lock()),
        io::stdout().lock(),
        io::stderr().lock(),
        AgentIdentity {
            name: "prism-ppo",
            version: "0.1.0",
        },
        seed,
        policy,
    )
    .map_err(|_| "Prism PPO agent runtime failed".to_string())
}

fn read_bounded(path: &Path, max_bytes: u64, kind: &str) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path).map_err(|_| format!("cannot inspect {kind} input"))?;
    if !metadata.is_file() || metadata.len() > max_bytes {
        return Err(format!("{kind} input exceeds the supported size"));
    }
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| format!("cannot open {kind} input"))?
        .take(max_bytes + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| format!("cannot read {kind} input"))?;
    if bytes.len() as u64 > max_bytes {
        return Err(format!("{kind} input exceeds the supported size"));
    }
    Ok(bytes)
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// A bounded byte-oriented JSONL iterator. Reading the whole file happens
/// before parsing, so even malformed/trailing bytes are included in the audit
/// input hash and cannot be silently ignored.
struct JsonLines<'a> {
    bytes: &'a [u8],
    cursor: usize,
    rows: usize,
}

impl<'a> JsonLines<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self {
            bytes,
            cursor: 0,
            rows: 0,
        }
    }

    fn next(&mut self) -> Result<Option<&'a [u8]>, String> {
        if self.cursor >= self.bytes.len() {
            return Ok(None);
        }
        let rest = &self.bytes[self.cursor..];
        let length = rest.iter().position(|b| *b == b'\n').unwrap_or(rest.len());
        let mut line = &rest[..length];
        self.cursor += length + usize::from(length < rest.len());
        if line.ends_with(b"\r") {
            line = &line[..line.len() - 1];
        }
        self.rows += 1;
        if self.rows > MAX_SIDECAR_ROWS || line.is_empty() || line.len() > MAX_MESSAGE_BYTES {
            return Err("invalid, empty, or oversized sidecar row".into());
        }
        Ok(Some(line))
    }
}

// Typed engine DTOs do not uniformly deny unknown fields. Check structural
// keys recursively, NOT f32 JSON decimal spelling (which changes on roundtrip).
fn same_json_shape(expected: &Value, actual: &Value) -> bool {
    match (expected, actual) {
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(k, v)| b.get(k).map(|x| same_json_shape(v, x)).unwrap_or(false))
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| same_json_shape(a, b))
        }
        (Value::Number(_), Value::Number(_)) => true,
        _ => expected == actual,
    }
}

fn parse_decision_row(line: &[u8]) -> Result<(DecisionRow, Value), String> {
    strict_json_keys(line)?;
    let row: DecisionRow = serde_json::from_slice(line)
        .map_err(|_| "sidecar row does not match the strict decision schema")?;
    row.request.input.validate()?;
    let raw: Value = serde_json::from_slice(line).map_err(|_| "sidecar row is not valid JSON")?;
    let canonical = serde_json::to_value(&row).map_err(|_| "cannot validate sidecar row")?;
    if !same_json_shape(&canonical, &raw) {
        return Err("sidecar row contains unknown or missing nested fields".into());
    }
    Ok((row, raw))
}

fn strict_json_keys(bytes: &[u8]) -> Result<(), String> {
    // Traverse before Value deserialization can erase duplicate object keys.
    struct Unique;
    impl<'de> Deserialize<'de> for Unique {
        fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
            struct Visitor;
            impl<'de> serde::de::Visitor<'de> for Visitor {
                type Value = Unique;
                fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                    f.write_str("JSON with unique object keys")
                }
                fn visit_map<A: serde::de::MapAccess<'de>>(
                    self,
                    mut map: A,
                ) -> Result<Unique, A::Error> {
                    let mut keys = std::collections::BTreeSet::new();
                    while let Some(key) = map.next_key::<String>()? {
                        if !keys.insert(key) {
                            return Err(serde::de::Error::custom("duplicate JSON key"));
                        }
                        map.next_value::<Unique>()?;
                    }
                    Ok(Unique)
                }
                fn visit_seq<A: serde::de::SeqAccess<'de>>(
                    self,
                    mut seq: A,
                ) -> Result<Unique, A::Error> {
                    while seq.next_element::<Unique>()?.is_some() {}
                    Ok(Unique)
                }
                fn visit_bool<E: serde::de::Error>(self, _: bool) -> Result<Unique, E> {
                    Ok(Unique)
                }
                fn visit_i64<E: serde::de::Error>(self, _: i64) -> Result<Unique, E> {
                    Ok(Unique)
                }
                fn visit_u64<E: serde::de::Error>(self, _: u64) -> Result<Unique, E> {
                    Ok(Unique)
                }
                fn visit_f64<E: serde::de::Error>(self, _: f64) -> Result<Unique, E> {
                    Ok(Unique)
                }
                fn visit_str<E: serde::de::Error>(self, _: &str) -> Result<Unique, E> {
                    Ok(Unique)
                }
                fn visit_unit<E: serde::de::Error>(self) -> Result<Unique, E> {
                    Ok(Unique)
                }
            }
            d.deserialize_any(Visitor)
        }
    }
    serde_json::from_slice::<Unique>(bytes)
        .map(|_| ())
        .map_err(|_| "invalid JSON or duplicate key".into())
}

fn validate_audit_request(
    request: &RequestBody,
    behavior_id: &str,
    job_id: &str,
    game_id: &str,
    actor: u8,
    request_id: u64,
    decision_index: u64,
    expected_input: &EncodedState,
) -> Result<(), String> {
    if request.format != REQUEST_FORMAT
        || request.behavior_id != behavior_id
        || request.job_id != job_id
        || request.game_id != game_id
        || request.actor != actor
        || request.request_id != request_id
        || request.decision_index != decision_index
        || request.catalog_fingerprint != catalog_fingerprint()
        || request.input != *expected_input
    {
        return Err("sidecar request identity, sequence, catalog, or encoding mismatch".into());
    }
    Ok(())
}

fn audit_command(args: &[String]) -> Result<(), String> {
    let opts = options(
        args,
        &[
            "--replay",
            "--sidecar",
            "--output",
            "--behavior-id",
            "--job-id",
            "--actor",
        ],
    )?;
    let behavior_id = required(&opts, "--behavior-id")?;
    validate_behavior_id(behavior_id)?;
    let job_id = required(&opts, "--job-id")?;
    validate_text(job_id, "job-id")?;
    let actor = match required(&opts, "--actor")? {
        "0" => 0,
        "1" => 1,
        _ => return Err("actor must be 0 or 1".into()),
    };
    let replay_bytes = read_bounded(
        Path::new(required(&opts, "--replay")?),
        MAX_REPLAY_BYTES,
        "replay",
    )?;
    strict_json_keys(&replay_bytes)?;
    let replay: ReplayV1 = serde_json::from_slice(&replay_bytes)
        .map_err(|_| "replay is not a strict ReplayV1 document".to_string())?;
    if replay.format != REPLAY_FORMAT
        || replay.version != REPLAY_VERSION
        || replay.player_count != 2
    {
        return Err("audit requires a terminal two-player ReplayV1".into());
    }
    let trace =
        verify_replay_trace(&replay).map_err(|_| "replay failed strict rules verification")?;
    if trace.verified.player_count != 2 || trace.positions.is_empty() {
        return Err("audit requires a nonempty two-player terminal trace".into());
    }
    let terminal_step = trace.positions.last().ok_or("empty replay trace")?;
    let mut terminal_state = terminal_step.state.clone();
    terminal_state
        .apply(terminal_step.recorded_action)
        .map_err(|_| "replay terminal transition could not be reconstructed")?;
    if !terminal_state.is_terminal() {
        return Err("audit rejects capped or nonterminal replay traces".into());
    }
    let result: GameResult = terminal_state
        .result
        .clone()
        .ok_or("terminal replay is missing its referee result")?;
    if !replay.result.matches(&result) {
        return Err("replay and reconstructed terminal result disagree".into());
    }

    let sidecar_bytes = read_bounded(
        Path::new(required(&opts, "--sidecar")?),
        MAX_SIDECAR_BYTES,
        "sidecar",
    )?;
    if !sidecar_bytes.ends_with(b"\n") {
        return Err("incomplete sidecar: last row must end in a newline".into());
    }
    let expected_count = trace
        .positions
        .iter()
        .filter(|step| step.recorded_actor.0 == actor)
        .count();
    if expected_count == 0 {
        return Err("requested actor has no decisions in this replay".into());
    }
    let mut lines = JsonLines::new(&sidecar_bytes);
    let mut decisions = Vec::with_capacity(expected_count);
    let mut game_id: Option<String> = None;
    let mut actor_decision_index = 0u64;
    let mut seen_request_ids = BTreeMap::<u64, ()>::new();
    for step in trace
        .positions
        .iter()
        .filter(|step| step.recorded_actor.0 == actor)
    {
        let line = lines
            .next()?
            .ok_or("sidecar is missing an actor decision")?;
        let (row, raw) = parse_decision_row(line)?;
        if row.format != DECISION_FORMAT
            || row.request.actor != actor
            || row.response.actor != actor
            || row.observation.viewer != PlayerId(actor)
            || row.observation.public.current_player != PlayerId(actor)
            || row.observation.public.player_count != 2
        {
            return Err("sidecar decision format or actor mismatch".into());
        }
        let this_game_id = row.request.game_id.clone();
        if this_game_id.is_empty() {
            return Err("sidecar game_id must be nonempty".into());
        }
        match &game_id {
            Some(expected) if expected != &this_game_id => {
                return Err("sidecar spans more than one game identity".into())
            }
            None => game_id = Some(this_game_id.clone()),
            _ => {}
        }
        let request_id = u64::from(step.ply)
            .checked_add(1)
            .ok_or("replay request id overflow")?;
        if seen_request_ids.insert(request_id, ()).is_some() {
            return Err("duplicate actor request id".into());
        }
        if step.recorded_actor != step.state.current_player {
            return Err("replay trace actor does not match current player".into());
        }
        let observation = step.state.observation(step.recorded_actor);
        let legal_actions = step.state.legal_actions();
        let visible_history =
            visible_events(&step.state.log, Audience::Player(step.recorded_actor));
        let input = encode(&observation, &visible_history, &legal_actions)?;
        validate_audit_request(
            &row.request,
            behavior_id,
            job_id,
            &this_game_id,
            actor,
            request_id,
            actor_decision_index,
            &input,
        )?;
        validate_response(&row.response, &row.request, legal_actions.len())?;
        let chosen_action = *legal_actions
            .get(row.response.chosen_index)
            .ok_or("sidecar selected action index is out of range")?;
        if row.response.chosen_index >= row.request.input.actions.len()
            || chosen_action != step.recorded_action
            || row.chosen_action != chosen_action
            || row.observation != observation
            || row.visible_history != visible_history
            || row.legal_actions != legal_actions
        {
            return Err("sidecar action or player-view replay projection mismatch".into());
        }
        // Typed nested engine records do not all deny unknown fields; require
        // their serialized representation to equal the submitted JSON too.
        let canonical = serde_json::to_value(&row).map_err(|_| "cannot validate sidecar row")?;
        if !same_json_shape(&canonical, &raw) {
            return Err("sidecar contains unknown nested fields".into());
        }
        decisions.push(row);
        actor_decision_index = actor_decision_index
            .checked_add(1)
            .ok_or("actor decision index overflow")?;
    }
    if lines.next()?.is_some() {
        return Err("sidecar has extra rows after the actor trajectory".into());
    }
    let game_id = game_id.ok_or("empty actor trajectory")?;
    let audit = json!({
        "format": AUDIT_FORMAT,
        "behavior_id": behavior_id,
        "job_id": job_id,
        "actor": actor,
        "game_id": game_id,
        "catalog_fingerprint": catalog_fingerprint(),
        "replay_sha256": sha256(&replay_bytes),
        "sidecar_sha256": sha256(&sidecar_bytes),
        "terminal": true,
        "result": result,
        "decisions": decisions,
    });
    let output_bytes =
        serde_json::to_vec(&audit).map_err(|_| "cannot serialize completed audit result")?;
    if output_bytes.len() as u64 > MAX_SIDECAR_BYTES + 16_384 {
        return Err("audit output exceeds supported size".into());
    }
    let output_path = Path::new(required(&opts, "--output")?);
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output_path)
        .map_err(|_| "audit output must be a new writable file".to_string())?;
    output
        .write_all(&output_bytes)
        .and_then(|_| output.write_all(b"\n"))
        .and_then(|_| output.flush())
        .and_then(|_| output.sync_all())
        .map_err(|_| "cannot durably write audit output".to_string())?;
    Ok(())
}

/// Entry point for the parent CLI dispatch. `main.rs` should route both
/// `agent-prism-ppo` and `prism-ppo-audit` here without changing old Prism
/// command behavior.
pub fn run(command: &str, args: &[String]) -> i32 {
    let result = match command {
        "agent-prism-ppo" => run_agent_command(args),
        "prism-ppo-audit" => audit_command(args),
        _ => Err("unknown Prism PPO command".into()),
    };
    match result {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("Prism PPO error: {error}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{FullState, GameConfig, Ruleset};

    fn fixture_request_and_input() -> (RequestBody, Vec<Action>) {
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 7,
            ruleset: Ruleset::base_v1(),
        })
        .unwrap();
        let actor = state.current_player;
        let actions = state.legal_actions();
        let history = visible_events(&state.log, Audience::Player(actor));
        let input = encode(&state.observation(actor), &history, &actions).unwrap();
        let request = RequestBody {
            format: REQUEST_FORMAT.into(),
            behavior_id: "a".repeat(64),
            job_id: "synthetic-job".into(),
            game_id: "synthetic-game".into(),
            actor: actor.0,
            request_id: 1,
            decision_index: 0,
            catalog_fingerprint: catalog_fingerprint(),
            input,
        };
        (request, actions)
    }

    fn response_for(
        request: &RequestBody,
        probabilities: Vec<f64>,
        chosen_index: usize,
    ) -> PpoResponse {
        PpoResponse {
            format: RESPONSE_FORMAT.into(),
            behavior_id: request.behavior_id.clone(),
            job_id: request.job_id.clone(),
            game_id: request.game_id.clone(),
            actor: request.actor,
            request_id: request.request_id,
            decision_index: request.decision_index,
            chosen_index,
            log_prob: probabilities[chosen_index].ln(),
            value: 0.5,
            style_value: -0.25,
            probabilities,
        }
    }

    #[test]
    fn loopback_requires_numeric_exact_ipv4_endpoint() {
        assert!(validate_endpoint("127.0.0.1:1234").is_ok());
        for invalid in [
            "localhost:1234",
            "[::1]:1234",
            "0.0.0.0:1234",
            "127.0.0.2:1",
            "127.0.0.1:0",
        ] {
            assert!(validate_endpoint(invalid).is_err(), "accepted {invalid}");
        }
    }

    #[test]
    fn response_checks_action_distribution_identity_and_values() {
        let (request, actions) = fixture_request_and_input();
        let probabilities = vec![1.0 / actions.len() as f64; actions.len()];
        let mut response = response_for(&request, probabilities, 0);
        // Correct the final floating-point normalization without relaxing the
        // 1e-10 wire tolerance.
        let prior: f64 = response.probabilities.iter().sum();
        response.probabilities[0] += 1.0 - prior;
        response.log_prob = response.probabilities[0].ln();
        validate_response(&response, &request, actions.len()).unwrap();

        let mut mismatch = response.clone();
        mismatch.request_id += 1;
        assert!(validate_response(&mismatch, &request, actions.len()).is_err());
        let mut unnormalized = response.clone();
        unnormalized.probabilities[0] += 0.01;
        unnormalized.log_prob = unnormalized.probabilities[0].ln();
        assert!(validate_response(&unnormalized, &request, actions.len()).is_err());
        let mut invalid_value = response;
        invalid_value.value = 1.01;
        assert!(validate_response(&invalid_value, &request, actions.len()).is_err());
    }

    #[test]
    fn request_and_decision_sidecar_never_serialize_token() {
        let (request, actions) = fixture_request_and_input();
        let wire = WireRequest {
            format: REQUEST_FORMAT,
            token: "synthetic-secret",
            behavior_id: &request.behavior_id,
            job_id: &request.job_id,
            game_id: &request.game_id,
            actor: request.actor,
            request_id: request.request_id,
            decision_index: request.decision_index,
            catalog_fingerprint: &request.catalog_fingerprint,
            input: &request.input,
        };
        let wire_text = serde_json::to_string(&wire).unwrap();
        assert!(wire_text.contains("synthetic-secret"));
        let response = response_for(&request, vec![1.0; actions.len()], 0);
        let row = DecisionRow {
            format: DECISION_FORMAT.into(),
            request,
            response,
            observation: serde_json::from_value(json!({})).unwrap_or_else(|_| {
                let (state, _) = FullState::new(GameConfig {
                    player_count: 2,
                    seed: 7,
                    ruleset: Ruleset::base_v1(),
                })
                .unwrap();
                state.observation(PlayerId(0))
            }),
            visible_history: Vec::new(),
            legal_actions: actions.clone(),
            chosen_action: actions[0],
        };
        let sidecar = serde_json::to_string(&row).unwrap();
        assert!(!sidecar.contains("synthetic-secret"));
        assert!(parse_decision_row(sidecar.as_bytes()).is_ok());
        assert!(!serde_json::to_value(&row.request)
            .unwrap()
            .as_object()
            .unwrap()
            .contains_key("token"));
    }

    #[test]
    fn strict_sidecar_rows_reject_missing_unknown_and_trailing_garbage() {
        assert!(parse_decision_row(b"{}").is_err());
        assert!(parse_decision_row(b"{\"format\":\"x\",\"unknown\":1}").is_err());
        assert!(parse_decision_row(b"not-json").is_err());
        let mut lines = JsonLines::new(b"{}\ntrailing-junk");
        assert_eq!(lines.next().unwrap(), Some(&b"{}"[..]));
        assert_eq!(lines.next().unwrap(), Some(&b"trailing-junk"[..]));
        assert_eq!(lines.next().unwrap(), None);
    }

    #[test]
    fn audit_sequence_requires_actor_decision_index_and_global_request_id() {
        let (mut request, _) = fixture_request_and_input();
        request.request_id = 3;
        assert!(validate_audit_request(
            &request,
            &request.behavior_id,
            &request.job_id,
            &request.game_id,
            request.actor,
            2,
            0,
            &request.input,
        )
        .is_err());
        request.request_id = 2;
        request.decision_index = 1;
        assert!(validate_audit_request(
            &request,
            &request.behavior_id,
            &request.job_id,
            &request.game_id,
            request.actor,
            2,
            0,
            &request.input,
        )
        .is_err());
    }

    #[test]
    fn one_synthetic_player_view_encodes_without_referee_features() {
        let (request, actions) = fixture_request_and_input();
        request.input.validate().unwrap();
        assert_eq!(request.actor, 0);
        assert!(!actions.is_empty());
        let text = serde_json::to_string(&request.input).unwrap();
        assert!(!text.contains("seed"));
        assert!(!text.contains("hash"));
        assert!(!text.contains("synthetic-secret"));
    }
}

#[cfg(test)]
#[path = "prism_ppo_tests.rs"]
mod integration_tests;
