"""M46A frozen corpus generator: n1 self-play games -> per-game NPZ shards.

Phases (run in order; each skips already-complete outputs for resume):
  matches: run 2-player n1-vs-n1 self-play (attribution profile `full`,
           identical n1 shell) for the frozen seed ranges into
           local-artifacts/m46a-corpus/games/{train,val,test}/seed-<s>/.
  expand:  run `m46a-generate-corpus` per replay -> per-game game.json.
  pack:    convert each game.json to a compressed per-game shard.npz and
           delete the JSON (streaming; bounds re-asserted in Python).
  audit:   split/identity/successor-hash audits (fail closed) + manifests.

Frozen seed ranges (inclusive):
  train: 6_600_000 .. 6_602_047 = 2048 games
  val:   6_602_048 .. 6_602_303 =  256 games
  test:  6_602_304 .. 6_602_559 =  256 games

Shard layout per game (R=8 roots, A=Amax actions in game, D=4, P=2):
  card        uint8  (R,A,D,P,15,39)  market(role 0)+own reserved(role 1)
  noble       uint8  (R,A,D,P,5,12)   visible nobles
  praw        uint8  (R,A,D,P,26)     self then opponent public raw
  glob        uint8  (R,A,D,P,13)     bank, decks, endgame state
  n_actions   int64  (R,)
  n_cards     int64  (R,A,D,P)   explicit card presence counts (mask)
  n_nobles    int64  (R,A,D,P)   explicit noble presence counts (mask)
  terminal    bool   (R,A,D)
  teacher_util int64 (R,A,D,2)        StaticEvaluatorV1 utilities vector
  progress    int64  (R,A,D,2)        nonterminal per-player progress
  mech        int64  (R,A,D,2,4)      [affordable_count, max_prestige,
                                      claimable, min_deficit(255 if none)]
  has_nobles  bool   (R,A,D,2)
  state_hash  S64    (R,A,D)          full-state hash of successor
  root_identity S64   (R,3)           authoritative triple per root
  root_meta   int64  (R,3)            [step_index, decision_ply, actor]
  game_seed   int64  scalar
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/m46a-corpus"

SAMPLE_SEED = 20_260_703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
MAX_NODES = 1

SPLITS = {
    "train": (6_600_000, 6_602_047),
    "val": (6_602_048, 6_602_303),
    "test": (6_602_304, 6_602_559),
}

MAX_CARDS = 15
MAX_NOBLES = 5
N_DETS = 4
N_PLAYERS = 2
ROOTS_PER_GAME = 8


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_spec() -> dict:
    return {
        "program": str(SPLN),
        "args": [
            "agent-determinization",
            "--sample-seed", str(SAMPLE_SEED),
            "--sample-count", str(SAMPLE_COUNT),
            "--max-depth-turns", str(DEPTH_TURNS),
            "--max-nodes", str(MAX_NODES),
            "--attribution-profile", "full",
            "--runtime-name", "m46a-n1-selfplay",
            "--runtime-version", "1",
        ],
    }


def run_one_match(split: str, seed: int) -> dict:
    gdir = OUT_ROOT / "games" / split / f"seed-{seed}"
    gdir.mkdir(parents=True, exist_ok=True)
    cfg_path = gdir / "match-config.json"
    rep_path = gdir / "arena-report.json"
    rpl_path = gdir / "match-replay.json"
    if rep_path.exists() and rpl_path.exists():
        report = json.loads(rep_path.read_text(encoding="utf-8"))
        if report.get("outcome", {}).get("status") == "completed":
            return {"seed": seed, "skipped": True}
    spec = agent_spec()
    cfg = {
        "game_id": f"m46a-corpus-{split}-seed-{seed}",
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": [spec, spec],
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    res = subprocess.run(
        [str(SPLN), "run-match", "--config", str(cfg_path),
         "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"match seed {seed} failed ({res.returncode}): {res.stderr[-2000:]}")
    report = json.loads(rep_path.read_text(encoding="utf-8"))
    if report.get("outcome", {}).get("status") != "completed":
        raise RuntimeError(f"match seed {seed} non-completed: {report.get('outcome')}")
    return {"seed": seed, "skipped": False,
            "plies": report["outcome"].get("completed_plies")}


def phase_matches(workers: int) -> None:
    tasks = [(split, s) for split, (a, b) in SPLITS.items() for s in range(a, b + 1)]
    print(f"Phase matches: {len(tasks)} games, {workers} workers", flush=True)
    done = skipped = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one_match, sp, s): (sp, s) for sp, s in tasks}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            done += 1
            skipped += 1 if r.get("skipped") else 0
            if done % 256 == 0:
                print(f"  matches {done}/{len(tasks)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"Phase matches done: {done} games ({skipped} skipped), {time.time()-t0:.0f}s", flush=True)


def expand_one(split: str, seed: int) -> dict:
    gdir = OUT_ROOT / "games" / split / f"seed-{seed}"
    rpl = gdir / "match-replay.json"
    out = gdir / "game.json"
    if out.exists():
        return {"seed": seed, "skipped": True}
    if not rpl.exists():
        raise RuntimeError(f"missing replay for {split} seed {seed}")
    res = subprocess.run(
        [str(SPLN), "m46a-generate-corpus", "--replay", str(rpl), "--out", str(out)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"expand {split} seed {seed} failed: {res.stderr[-2000:]}")
    return {"seed": seed, "skipped": False}


def phase_expand(workers: int) -> None:
    tasks = [(split, s) for split, (a, b) in SPLITS.items() for s in range(a, b + 1)]
    print(f"Phase expand: {len(tasks)} games, {workers} workers", flush=True)
    done = skipped = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(expand_one, sp, s): (sp, s) for sp, s in tasks}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            done += 1
            skipped += 1 if r.get("skipped") else 0
            if done % 128 == 0:
                print(f"  expand {done}/{len(tasks)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"Phase expand done: {done} games ({skipped} skipped), {time.time()-t0:.0f}s", flush=True)


def pack_one(split: str, seed: int) -> dict:
    import numpy as np

    gdir = OUT_ROOT / "games" / split / f"seed-{seed}"
    jpath = gdir / "game.json"
    spath = gdir / "shard.npz"
    if spath.exists():
        return {"seed": seed, "skipped": True}
    g = json.loads(jpath.read_text(encoding="utf-8"))
    if g["player_count"] != 2:
        raise RuntimeError(f"{split} seed {seed}: player_count != 2")
    if len(g["roots"]) != ROOTS_PER_GAME:
        raise RuntimeError(f"{split} seed {seed}: roots != 8")
    amax = max(len(r["actions"]) for r in g["roots"])
    R, A, D, P = ROOTS_PER_GAME, amax, N_DETS, N_PLAYERS

    card = np.zeros((R, A, D, P, MAX_CARDS, 39), dtype=np.uint8)
    noble = np.zeros((R, A, D, P, MAX_NOBLES, 12), dtype=np.uint8)
    praw = np.zeros((R, A, D, P, 26), dtype=np.uint8)
    glob = np.zeros((R, A, D, P, 13), dtype=np.uint8)
    n_actions = np.zeros((R,), dtype=np.int64)
    n_cards = np.zeros((R, A, D, P), dtype=np.int64)
    n_nobles = np.zeros((R, A, D, P), dtype=np.int64)
    terminal = np.zeros((R, A, D), dtype=bool)
    teacher_util = np.zeros((R, A, D, P), dtype=np.int64)
    progress = np.zeros((R, A, D, P), dtype=np.int64)
    mech = np.zeros((R, A, D, P, 4), dtype=np.int64)
    has_nobles = np.zeros((R, A, D, P), dtype=bool)
    state_hash = np.zeros((R, A, D), dtype="S64")
    root_identity = np.zeros((R, 3), dtype="S64")
    root_meta = np.zeros((R, 3), dtype=np.int64)

    for ri, r in enumerate(g["roots"]):
        n_actions[ri] = len(r["actions"])
        root_identity[ri] = [r["identity"]["observation_hash"],
                             r["identity"]["visible_history_hash"],
                             r["identity"]["information_set_hash"]]
        root_meta[ri] = [r["step_index"], r["decision_ply"], r["actor"]]
        for ai, a in enumerate(r["actions"]):
            if len(a["successors"]) != N_DETS:
                raise RuntimeError(f"{split} seed {seed} root {ri}: dets != 4")
            for si, s in enumerate(a["successors"]):
                terminal[ri, ai, si] = s["terminal"]
                if len(s["teacher_utility"]) != 2 or len(s["progress"]) != 2:
                    raise RuntimeError("utility/progress shape")
                teacher_util[ri, ai, si] = s["teacher_utility"]
                progress[ri, ai, si] = s["progress"]
                state_hash[ri, ai, si] = s["state_hash"].encode()
                if len(s["players"]) != 2:
                    raise RuntimeError("players != 2")
                for pi, pf in enumerate(s["players"]):
                    n_cards[ri, ai, si, pi] = len(pf["cards"])
                    n_nobles[ri, ai, si, pi] = len(pf["nobles"])
                    if len(pf["cards"]) > MAX_CARDS:
                        raise RuntimeError("cards exceed 15")
                    for ci, c in enumerate(pf["cards"]):
                        card[ri, ai, si, pi, ci] = (
                            c["cost"] + [c["prestige"], c["tier"], c["bonus"], c["role"]]
                            + c["discounted"] + c["shortfall"]
                            + [c["gold_needed"], int(c["affordable"])]
                        )
                    if len(pf["nobles"]) > MAX_NOBLES:
                        raise RuntimeError("nobles exceed 5")
                    for ni, nb in enumerate(pf["nobles"]):
                        noble[ri, ai, si, pi, ni] = (
                            nb["req"] + [nb["prestige"]] + nb["deficit"] + [int(nb["claimable"])]
                        )
                    if len(pf["player_raw"]) != 26 or len(pf["global_raw"]) != 13:
                        raise RuntimeError("raw feature length")
                    praw[ri, ai, si, pi] = pf["player_raw"]
                    glob[ri, ai, si, pi] = pf["global_raw"]
                    if pf["affordable_count"] > 15 or pf["max_prestige"] > 5 \
                            or pf["claimable"] > 5 \
                            or (pf["has_nobles"] and pf["min_deficit"] > 20):
                        raise RuntimeError(f"mechanics label out of range: {pf}")
                    mech[ri, ai, si, pi] = [pf["affordable_count"], pf["max_prestige"],
                                            pf["claimable"], pf["min_deficit"]]
                    has_nobles[ri, ai, si, pi] = pf["has_nobles"]

    np.savez_compressed(
        spath, card=card, noble=noble, praw=praw, glob=glob,
        n_actions=n_actions, n_cards=n_cards, n_nobles=n_nobles,
        terminal=terminal, teacher_util=teacher_util,
        progress=progress, mech=mech, has_nobles=has_nobles,
        state_hash=state_hash, root_identity=root_identity,
        root_meta=root_meta, game_seed=np.int64(g["game_seed"]),
    )
    jpath.unlink()
    return {"seed": seed, "skipped": False, "amax": amax}


def phase_pack(workers: int) -> None:
    tasks = [(split, s) for split, (a, b) in SPLITS.items() for s in range(a, b + 1)]
    print(f"Phase pack: {len(tasks)} games, {workers} workers", flush=True)
    done = skipped = 0
    amax_all = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(pack_one, sp, s): (sp, s) for sp, s in tasks}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            done += 1
            skipped += 1 if r.get("skipped") else 0
            amax_all = max(amax_all, r.get("amax", 0))
            if done % 256 == 0:
                print(f"  pack {done}/{len(tasks)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"Phase pack done: {done} ({skipped} skipped), max actions/game={amax_all}, {time.time()-t0:.0f}s",
          flush=True)


def phase_audit() -> None:
    import numpy as np

    print("Phase audit: split/identity/successor-hash checks (fail closed)", flush=True)
    manifest = {"splits": {}}
    all_root_identities: dict[str, list] = {"train": [], "val": [], "test": []}
    all_succ_hashes: dict[str, set] = {"train": set(), "val": set(), "test": set()}
    for split, (a, b) in SPLITS.items():
        seeds = list(range(a, b + 1))
        n_roots = n_succ = n_score = 0
        expected = (b - a + 1)
        found = 0
        for s in seeds:
            spath = OUT_ROOT / "games" / split / f"seed-{s}" / "shard.npz"
            if not spath.exists():
                raise RuntimeError(f"missing shard {split} seed {s}")
            found += 1
            z = np.load(spath)
            if int(z["game_seed"]) != s:
                raise RuntimeError("game_seed mismatch")
            if z["n_actions"].shape != (ROOTS_PER_GAME,) or (z["n_actions"] < 1).any():
                raise RuntimeError("n_actions shape/content")
            n_roots += ROOTS_PER_GAME
            for ri in range(ROOTS_PER_GAME):
                na = int(z["n_actions"][ri])
                trip = tuple(x.decode() for x in z["root_identity"][ri])
                if any(len(h) != 64 for h in trip):
                    raise RuntimeError("identity hash length")
                all_root_identities[split].append(trip)
                for ai in range(na):
                    for si in range(N_DETS):
                        h = z["state_hash"][ri, ai, si].decode()
                        if len(h) != 64:
                            raise RuntimeError("state hash length")
                        all_succ_hashes[split].add(h)
                        n_succ += 1
                        n_score += N_PLAYERS
        if found != expected:
            raise RuntimeError(f"{split}: found {found} != {expected}")
        # cross-split root identity disjointness
        manifest["splits"][split] = {
            "games": found, "roots": n_roots, "successors": n_succ,
            "scoring_examples": n_score,
            "unique_root_identities": len(set(all_root_identities[split])),
            "unique_successor_hashes": len(all_succ_hashes[split]),
        }
        print(f"  {split}: games={found} roots={n_roots} successors={n_succ} "
              f"score-ex={n_score} uniq-roots={len(set(all_root_identities[split]))} "
              f"uniq-succ={len(all_succ_hashes[split])}", flush=True)

    r_sets = {k: set(v) for k, v in all_root_identities.items()}
    for x, y in [("train", "val"), ("train", "test"), ("val", "test")]:
        if r_sets[x] & r_sets[y]:
            raise RuntimeError(f"cross-split root identity overlap {x}/{y}")
    for x, y in [("train", "val"), ("train", "test"), ("val", "test")]:
        if all_succ_hashes[x] & all_succ_hashes[y]:
            raise RuntimeError(f"cross-split successor hash overlap {x}/{y}")

    # identity digest per split
    for split in SPLITS:
        h = hashlib.sha256()
        h.update(b"effective-splendor-m46a-root-identities-v1\0")
        for trip in sorted(set(all_root_identities[split])):
            h.update(("|".join(trip) + "\n").encode())
        manifest["splits"][split]["root_identity_sha256"] = h.hexdigest()
    manifest["seed_ranges"] = {k: list(v) for k, v in SPLITS.items()}
    mp = OUT_ROOT / "corpus-manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"AUDIT PASS. Manifest: {mp}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="M46A frozen corpus generator")
    ap.add_argument("--phases", default="matches,expand,pack,audit")
    ap.add_argument("--match-workers", type=int, default=8)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    assert SPLN.exists(), f"missing binary {SPLN}"
    for ph in args.phases.split(","):
        ph = ph.strip()
        if ph == "matches":
            phase_matches(args.match_workers)
        elif ph == "expand":
            phase_expand(args.workers)
        elif ph == "pack":
            phase_pack(args.workers)
        elif ph == "audit":
            phase_audit()
        else:
            raise ValueError(f"unknown phase {ph}")
    print("M46A corpus pipeline complete.")


if __name__ == "__main__":
    main()
