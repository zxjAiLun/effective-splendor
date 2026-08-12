# M20 Human Play Studio

M20 adds a local, 1v1 human-vs-agent surface at `/play`. The browser is not a
referee: it receives only the human seat's `Observation`, server-certified
legal actions, public session metadata and the terminal result. It never
receives the raw game seed, deck order, `FullState`, or opponent blind-reserve
identity.

From the standard repository root, double-click:

```text
Start Splendor Studio.cmd
```

That single launcher builds the local binary when needed, starts the persistent
Studio Host and Replay Studio in the background, waits until both are healthy,
and opens `/play`. The page discovers every agent in the tracked Studio 1v1
registry, including M17/M18A/M18B/M22 GPU checkpoints. Choose a
baseline, search agent, or GPU checkpoint, then press **Start new game**. There
is no port field or manual Connect step.

The Host API owns session creation:

```text
GET  /agents
POST /games  { agent_id, human_seat, seed }
GET  /state
POST /action
GET  /archive
```

Open `http://127.0.0.1:4173/play`. Every action button is sourced from the
engine's current legal-action list. Market cards offer direct Buy buttons when
legal, while the complete action list includes token returns, reserve choices,
noble selection and forced pass.

The Host accepts any agent in a validated M16 rating registry, including local
GPU checkpoints, through the same strict Arena NDJSON handshake and
Observation/action protocol:

```powershell
target/debug/splendor.exe human-play-server `
  --seed 200002 --human-seat 0 --port 43120 `
  --registry local-artifacts/m19-internal-championship-v1/registry.json `
  --agent-id m18a-self-play
```

Registry identity, game/request ids, deadlines and the server-certified legal
action set are checked before a move reaches the engine. No command is joined
through a shell. The browser's public `/agents` response deliberately omits
registry command lines and local checkpoint paths.

`human-play-server` remains available as a low-level diagnostic command, but it
is not the normal user workflow.

Every completed match is verified as Replay v1 and written without overwrite
under `local-artifacts/m20-human-play/` by default. The terminal screen's
**Open verified game in Replay Studio** button carries the verified replay and
per-decision actor `Observation` frames into the existing studio in the same
browser session. This audit mode remains player-view-only; it does not expose
the replay seed or deck order before the game ends, and it does not fabricate
search statistics when no AnalysisTrace sidecar exists.
