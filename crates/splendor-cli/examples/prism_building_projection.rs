//! M62 read-only, terminal-replay player perspective exporter.
//! Build against the frozen M57 workspace, without changing its engine or manifests.
//! Usage: prism_building_projection manifest.json output.json
//!        [--panel-max-games 64 --panel-output panel.jsonl]
//! Manifest: ordered array of {replay_path}, or {rows:[...]}/{games:[...]}.
//! Relative replay paths resolve against the manifest directory. Seed duplication
//! across distinct replay files is allowed; canonical replay paths must be unique.
//! This is offline provenance: seeds/hashes are never passed to the Prism encoder.
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use splendor_core::{visible_events, Action, Audience, Observation, Phase, PlayerId};
use splendor_prism::{catalog_fingerprint, encode, EncodedState};
use splendor_replay::{verify_replay_trace, ReplayGameResultV1, ReplayV1};
use std::{
    collections::HashSet,
    error::Error,
    ffi::OsString,
    fs::{self, File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

type ExportResult<T> = Result<T, Box<dyn Error>>;
const FORMAT: &str = "prism-building-projection-v1";
const PANEL_MAINS: [u32; 3] = [4, 8, 12];
const MAX_PANEL_GAMES: usize = 64;

#[derive(Debug)]
struct ReplayInput {
    replay_path: String,
    resolved_path: PathBuf,
    expected_sha256: Option<String>,
}

#[derive(Serialize)]
struct Decision {
    ply: u32,
    observation: Observation,
    chosen_action: Action,
}

#[derive(Serialize)]
struct PlayerProjection {
    actor: PlayerId,
    decisions: Vec<Decision>,
}

#[derive(Serialize)]
struct GameProjection {
    replay_path: String,
    replay_sha256: String,
    seed: u64,
    catalog_fingerprint: String,
    terminal: bool,
    result: ReplayGameResultV1,
    players: Vec<PlayerProjection>,
}

#[derive(Serialize)]
struct PanelRow {
    replay_path: String,
    replay_sha: String,
    ply: u32,
    actor: PlayerId,
    own_main: u32,
    observation: Observation,
    legal_actions: Vec<Action>,
    chosen_action: Action,
    input: EncodedState,
}

struct Options {
    manifest: PathBuf,
    output: PathBuf,
    panel_output: Option<PathBuf>,
    panel_max_games: usize,
}

fn options(args: Vec<OsString>) -> ExportResult<Options> {
    const USAGE: &str = "usage: prism_building_projection <manifest.json> <output.json> [--panel-max-games 1..64 --panel-output <jsonl>]";
    if args.len() < 2 {
        return Err(USAGE.into());
    }
    let mut opts = Options {
        manifest: PathBuf::from(&args[0]),
        output: PathBuf::from(&args[1]),
        panel_output: None,
        panel_max_games: MAX_PANEL_GAMES,
    };
    let mut explicit_max = false;
    let mut i = 2;
    while i < args.len() {
        let value = args.get(i + 1).ok_or(USAGE)?;
        match args[i].to_str() {
            Some("--panel-output") if opts.panel_output.is_none() => {
                opts.panel_output = Some(PathBuf::from(value));
            }
            Some("--panel-max-games") if !explicit_max => {
                opts.panel_max_games = value.to_str().ok_or(USAGE)?.parse()?;
                explicit_max = true;
            }
            _ => return Err(USAGE.into()),
        }
        i += 2;
    }
    if !(1..=MAX_PANEL_GAMES).contains(&opts.panel_max_games)
        || (explicit_max && opts.panel_output.is_none())
    {
        return Err(USAGE.into());
    }
    Ok(opts)
}

fn manifest_inputs(manifest_path: &Path) -> ExportResult<Vec<ReplayInput>> {
    let manifest: Value = serde_json::from_slice(&fs::read(manifest_path)?)?;
    let rows = match &manifest {
        Value::Array(rows) => rows,
        Value::Object(object) => {
            if object.contains_key("rows") && object.contains_key("games") {
                return Err("manifest must have exactly one ordered rows/games array".into());
            }
            object
                .get("rows")
                .or_else(|| object.get("games"))
                .and_then(Value::as_array)
                .ok_or("manifest requires an ordered rows/games array")?
        }
        _ => return Err("manifest requires an ordered array".into()),
    };
    if rows.is_empty() {
        return Err("manifest must contain at least one replay".into());
    }
    let parent = manifest_path.parent().unwrap_or(Path::new("."));
    let mut seen = HashSet::new();
    rows.iter()
        .enumerate()
        .map(|(index, row)| {
            let replay_path = row["replay_path"]
                .as_str()
                .filter(|p| !p.is_empty())
                .ok_or_else(|| format!("manifest row {index}: missing replay_path"))?;
            let resolved_path = fs::canonicalize(parent.join(replay_path))
                .map_err(|e| format!("manifest row {index} ({replay_path}): {e}"))?;
            if !resolved_path.is_file() || !seen.insert(resolved_path.clone()) {
                return Err(format!(
                    "manifest row {index}: non-file or duplicate replay_path {replay_path}"
                )
                .into());
            }
            let expected_sha256 = match row.get("replay_sha256") {
                None => None,
                Some(Value::String(hash))
                    if hash.len() == 64
                        && hash
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) =>
                {
                    Some(hash.clone())
                }
                _ => return Err(format!("manifest row {index}: invalid replay_sha256").into()),
            };
            Ok(ReplayInput {
                replay_path: replay_path.to_owned(),
                resolved_path,
                expected_sha256,
            })
        })
        .collect()
}

fn project_game(
    source: &ReplayInput,
    include_panel: bool,
) -> ExportResult<(GameProjection, Vec<PanelRow>)> {
    // Hash and deserialize the same bytes; never reopen an input for hashing.
    let bytes = fs::read(&source.resolved_path)?;
    let replay_sha256 = hex::encode(Sha256::digest(&bytes));
    if source
        .expected_sha256
        .as_ref()
        .is_some_and(|h| h != &replay_sha256)
    {
        return Err("manifest replay_sha256 mismatch".into());
    }
    let replay: ReplayV1 = serde_json::from_slice(&bytes)?;
    if replay.player_count != 2 {
        return Err("M62 projection requires a two-player terminal replay".into());
    }
    // Exactly one strict pass checks every step and the terminal suffix/result.
    let trace = verify_replay_trace(&replay)?;
    let fingerprint = catalog_fingerprint();
    if replay.ruleset_fingerprint.as_str() != fingerprint {
        return Err("Prism catalog fingerprint mismatch".into());
    }
    let mut players: Vec<PlayerProjection> = (0..replay.player_count)
        .map(|actor| PlayerProjection {
            actor: PlayerId(actor),
            decisions: Vec::new(),
        })
        .collect();
    let mut panel = Vec::new();
    let mut mains = [0u32; 2];
    for pos in trace.positions {
        let actor = pos.recorded_actor;
        if pos.state.current_player != actor || actor.index() >= players.len() {
            return Err("verified actor/current-player mismatch".into());
        }
        let observation = pos.state.observation(actor);
        if include_panel && pos.state.phase == Phase::Main {
            mains[actor.index()] += 1;
            let own_main = mains[actor.index()];
            if PANEL_MAINS.contains(&own_main) {
                let legal_actions = pos.state.legal_actions();
                let history = visible_events(&pos.state.log, Audience::Player(actor));
                let input = encode(&observation, &history, &legal_actions)?;
                input.validate()?;
                panel.push(PanelRow {
                    replay_path: source.replay_path.clone(),
                    replay_sha: replay_sha256.clone(),
                    ply: pos.ply,
                    actor,
                    own_main,
                    observation: observation.clone(),
                    legal_actions,
                    chosen_action: pos.recorded_action,
                    input,
                });
            }
        }
        // Only the acting player's observation is exported for this decision.
        // Never serialize the referee state, log, decks, or opponent privates.
        players[actor.index()].decisions.push(Decision {
            ply: pos.ply,
            observation,
            chosen_action: pos.recorded_action,
        });
    }
    if players.iter().map(|p| p.decisions.len()).sum::<usize>() != replay.steps.len() {
        return Err("projection decision count mismatch".into());
    }
    Ok((
        GameProjection {
            replay_path: source.replay_path.clone(),
            replay_sha256,
            seed: replay.seed,
            catalog_fingerprint: fingerprint,
            terminal: true,
            result: trace.verified.result,
            players,
        },
        panel,
    ))
}

// Stage in the destination directory and publish with a no-clobber hard link.
// These links concern only our new output files, never frozen source/cache files.
// A failed replay leaves neither a partial final export nor a published panel.
struct PendingOutput {
    destination: PathBuf,
    temporary: PathBuf,
    writer: Option<BufWriter<File>>,
    published: bool,
    keep: bool,
}

impl PendingOutput {
    fn create(path: &Path) -> ExportResult<Self> {
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let destination =
            fs::canonicalize(parent)?.join(path.file_name().ok_or("output filename")?);
        if destination.try_exists()? {
            return Err(format!("refusing to overwrite {}", destination.display()).into());
        }
        let mut name = destination
            .file_name()
            .ok_or("output filename")?
            .to_os_string();
        name.push(format!(".{}.projection-partial", std::process::id()));
        let temporary = destination.with_file_name(name);
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        Ok(Self {
            destination,
            temporary,
            writer: Some(BufWriter::new(file)),
            published: false,
            keep: false,
        })
    }

    fn writer(&mut self) -> &mut BufWriter<File> {
        self.writer
            .as_mut()
            .expect("writer exists until publication")
    }

    fn publish(&mut self) -> ExportResult<()> {
        let mut writer = self.writer.take().ok_or("output already published")?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        drop(writer);
        fs::hard_link(&self.temporary, &self.destination)?;
        self.published = true;
        fs::remove_file(&self.temporary)?;
        Ok(())
    }
}

impl Drop for PendingOutput {
    fn drop(&mut self) {
        drop(self.writer.take());
        let _ = fs::remove_file(&self.temporary);
        if self.published && !self.keep {
            let _ = fs::remove_file(&self.destination);
        }
    }
}

fn export(opts: Options) -> ExportResult<()> {
    let sources = manifest_inputs(&opts.manifest)?;
    let mut output = PendingOutput::create(&opts.output)?;
    let mut panel = opts
        .panel_output
        .as_deref()
        .map(PendingOutput::create)
        .transpose()?;
    if panel
        .as_ref()
        .is_some_and(|p| p.destination == output.destination)
    {
        return Err("output.json and panel.jsonl must be distinct paths".into());
    }
    write!(output.writer(), "{{\"format\":\"{FORMAT}\",\"games\":[")?;
    let mut decisions = 0usize;
    let mut panel_rows = 0usize;
    for (index, source) in sources.iter().enumerate() {
        let (game, rows) = project_game(source, panel.is_some() && index < opts.panel_max_games)
            .map_err(|e| format!("manifest row {index} ({}): {e}", source.replay_path))?;
        if index > 0 {
            output.writer().write_all(b",")?;
        }
        decisions += game
            .players
            .iter()
            .map(|p| p.decisions.len())
            .sum::<usize>();
        serde_json::to_writer(output.writer(), &game)?;
        if let Some(file) = panel.as_mut() {
            for row in rows {
                serde_json::to_writer(file.writer(), &row)?;
                file.writer().write_all(b"\n")?;
                panel_rows += 1;
            }
        }
    }
    output.writer().write_all(b"]}\n")?;
    if let Some(file) = panel.as_mut() {
        file.publish()?;
    }
    output.publish()?;
    output.keep = true;
    if let Some(file) = panel.as_mut() {
        file.keep = true;
    }
    println!(
        "PASS: verified {} terminal replays; {decisions} own decisions; {panel_rows} panel rows",
        sources.len()
    );
    Ok(())
}

fn main() {
    if let Err(error) = options(std::env::args_os().skip(1).collect()).and_then(export) {
        eprintln!("prism_building_projection: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> ReplayInput {
        let path = std::env::var_os("PRISM_PROJECTION_FIXTURE")
            .expect("set PRISM_PROJECTION_FIXTURE to an existing frozen terminal replay");
        ReplayInput {
            replay_path: PathBuf::from(&path).to_string_lossy().into_owned(),
            resolved_path: PathBuf::from(path),
            expected_sha256: None,
        }
    }

    #[test]
    fn panel_options_require_output_and_bound_encoding() {
        let args = |s: &[&str]| s.iter().map(OsString::from).collect();
        assert!(options(args(&["m.json", "o.json"])).is_ok());
        assert!(options(args(&["m.json", "o.json", "--panel-max-games", "64"])).is_err());
        assert!(options(args(&[
            "m.json",
            "o.json",
            "--panel-max-games",
            "65",
            "--panel-output",
            "p.jsonl"
        ]))
        .is_err());
        assert!(options(args(&["m.json", "o.json", "--panel-output", "p.jsonl"])).is_ok());
    }

    #[test]
    #[ignore = "requires an existing terminal replay via PRISM_PROJECTION_FIXTURE; never generates games"]
    fn saved_replay_covers_both_actors_and_uses_private_player_projection() {
        let source = fixture();
        let replay: ReplayV1 =
            serde_json::from_slice(&fs::read(&source.resolved_path).unwrap()).unwrap();
        let trace = verify_replay_trace(&replay).unwrap();
        let (game, panel) = project_game(&source, true).unwrap();
        assert_eq!(game.result, replay.result);
        assert_eq!(game.players.len(), 2);
        let mut decisions: Vec<_> = game.players.iter().flat_map(|p| &p.decisions).collect();
        decisions.sort_by_key(|d| d.ply);
        assert_eq!(decisions.len(), replay.steps.len());
        let mut saw_hidden_opponent = false;
        for (d, pos) in decisions.iter().zip(&trace.positions) {
            assert_eq!(d.ply, pos.ply);
            assert_eq!(d.chosen_action, pos.recorded_action);
            assert_eq!(d.observation.viewer, pos.recorded_actor);
            assert_eq!(d.observation, pos.state.observation(pos.recorded_actor));
            let actor = pos.recorded_actor.index();
            let opponent = 1 - actor;
            assert_eq!(
                d.observation.private.reserved.len(),
                pos.state.players[actor].reserved.len()
            );
            let opp_public = &d.observation.public.players[opponent];
            let actual_opponent = &pos.state.players[opponent];
            assert_eq!(
                opp_public.public_reserved.len(),
                actual_opponent
                    .reserved
                    .iter()
                    .filter(|r| !r.from_deck)
                    .count()
            );
            if actual_opponent.reserved.iter().any(|r| r.from_deck) {
                saw_hidden_opponent = true;
                assert!(opp_public.public_reserved.len() < actual_opponent.reserved.len());
            }
            let json = serde_json::to_value(d).unwrap();
            assert!(json.get("input").is_none());
            assert!(json["observation"].get("decks").is_none());
            assert!(json["observation"].get("log").is_none());
        }
        if std::env::var_os("PRISM_PROJECTION_REQUIRE_BLIND").is_some() {
            assert!(
                saw_hidden_opponent,
                "fixture must exercise a hidden opponent reserve"
            );
        }
        let mut mains = [0u32; 2];
        let mut expected_panel = Vec::new();
        for pos in &trace.positions {
            if pos.state.phase == Phase::Main {
                mains[pos.recorded_actor.index()] += 1;
                if PANEL_MAINS.contains(&mains[pos.recorded_actor.index()]) {
                    expected_panel.push((
                        pos.ply,
                        pos.recorded_actor,
                        mains[pos.recorded_actor.index()],
                    ));
                }
            }
        }
        assert_eq!(
            panel
                .iter()
                .map(|p| (p.ply, p.actor, p.own_main))
                .collect::<Vec<_>>(),
            expected_panel
        );
        for row in panel {
            let pos = &trace.positions[row.ply as usize];
            assert_eq!(row.legal_actions, pos.state.legal_actions());
            assert!(row.legal_actions.contains(&row.chosen_action));
            assert_eq!(
                row.input,
                encode(
                    &row.observation,
                    &visible_events(&pos.state.log, Audience::Player(row.actor)),
                    &row.legal_actions
                )
                .unwrap()
            );
            row.input.validate().unwrap();
        }
        let (_, default_panel) = project_game(&source, false).unwrap();
        assert!(default_panel.is_empty());
    }

    #[test]
    #[ignore = "requires an existing terminal replay via PRISM_PROJECTION_FIXTURE; never generates games"]
    fn saved_replay_rejects_suffix_tampering_and_nonterminal_prefix() {
        let replay: ReplayV1 =
            serde_json::from_slice(&fs::read(fixture().resolved_path).unwrap()).unwrap();
        let mut tampered = replay.clone();
        tampered.steps.last_mut().unwrap().actor = PlayerId(2);
        assert!(verify_replay_trace(&tampered).is_err());
        let mut prefix = replay;
        prefix.steps.truncate(1);
        assert!(verify_replay_trace(&prefix).is_err());
    }
}
