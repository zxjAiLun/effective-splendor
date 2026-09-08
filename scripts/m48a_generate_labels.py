"""M48A label generation: n1/n2000 per-root records for train/internal-test/val.

Reuses the audited `m47s-residual` Rust command (which already produces
full per-action utilities for budgets 1/200/500/2000 with cross-budget
action-set identity asserts). M48A consumes only the n1 and n2000 budgets.

Splits (frozen DESIGN_V2):
  train:          6_600_000 .. 6_601_791  (1792 games, 14336 roots)
  internal_test:  6_601_792 .. 6_602_047  (256 games, 2048 roots)
  validation:     6_602_048 .. 6_602_303  (256 games, 2048 roots)
  (M47S holdout 6_602_304..6_602_559 reuses existing M47S raw records)

Fail-closed throughout. No new self-play. No M47S holdout touch here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
CORPUS = REPO / "local-artifacts/m46a-corpus"
OUT_ROOT = REPO / "local-artifacts/m48a-run"
M47S_RAW = REPO / "local-artifacts/m47s-run/raw-records.json"

SPLITS = {
    "train": (6_600_000, 6_601_791),
    "internal_test": (6_601_792, 6_602_047),
    "validation": (6_602_048, 6_602_303),
}
M47S_HOLDOUT = (6_602_304, 6_602_559)
ROOTS_PER_GAME = 8


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def m46a_dir_for_seed(seed: int) -> Path:
    """Map a game seed to its M46A corpus directory (M46A layout: train
    6_600_000..6_602_047, val 6_602_048..6_602_303, test 6_602_304..6_602_559)."""
    if 6_600_000 <= seed <= 6_602_047:
        return CORPUS / "games" / "train"
    if 6_602_048 <= seed <= 6_602_303:
        return CORPUS / "games" / "val"
    raise RuntimeError(f"seed {seed} outside M46A train/val corpus")


def generate_split(split: str) -> list[dict]:
    a, b = SPLITS[split]
    games = []
    t0 = time.time()
    done = 0
    for seed in range(a, b + 1):
        gdir = m46a_dir_for_seed(seed) / f"seed-{seed}"
        rpl = gdir / "match-replay.json"
        shard = gdir / "shard.npz"
        out = OUT_ROOT / "labels" / split / f"seed-{seed}.json"
        roots_sidecar = OUT_ROOT / "labels" / split / f"seed-{seed}.roots.json"
        if out.exists():
            games.append(json.loads(out.read_text(encoding="utf-8")))
            done += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        z = np.load(shard)
        root_meta = z["root_meta"]
        roots_spec = [[int(r[0]), int(r[2])] for r in root_meta]
        roots_sidecar.write_text(json.dumps(roots_spec), encoding="utf-8")
        cmd = [str(SPLN), "m47s-residual",
               "--replay", str(rpl), "--shard", str(shard),
               "--roots", str(roots_sidecar), "--out", str(out)]
        last_err = ""
        for attempt in range(4):
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                break
            last_err = f"rc={res.returncode} stderr={res.stderr[-1500:]}"
            time.sleep(2.0 * (attempt + 1))
        else:
            raise RuntimeError(f"{split} seed {seed} failed after retries: {last_err}")
        games.append(json.loads(out.read_text(encoding="utf-8")))
        done += 1
        if done % 128 == 0:
            print(f"  {split}: {done}/{b-a+1} ({time.time()-t0:.0f}s)", flush=True)
    print(f"  {split}: {done}/{b-a+1} complete ({time.time()-t0:.0f}s)", flush=True)
    return games


def audit(games_by_split: dict[str, list[dict]]) -> dict:
    """All-pairs root-identity AND successor-state-hash disjointness across
    the four new splits (plus seed/budget/label sanity checks)."""
    label_sanity_checks(games_by_split)
    split_triples: dict[str, set] = {}
    split_succ: dict[str, set] = {}
    split_roots: dict[str, int] = {}
    for split, games in games_by_split.items():
        triples = set()
        succ = set()
        n = 0
        for g in games:
            z = load_shard_for_audit(g["game_seed"])
            for root in g["roots"]:
                triples.add((root["observation_hash"],
                             root["visible_history_hash"],
                             root["information_set_hash"]))
                ri = locate_root_index(z, root["step_index"])
                na = int(z["n_actions"][ri])
                for ai in range(na):
                    for si in range(4):
                        succ.add(z["state_hash"][ri, ai, si].decode())
                n += 1
        split_triples[split] = triples
        split_succ[split] = succ
        split_roots[split] = n

    # M47S holdout triples + successor hashes from existing raw records + shards
    m47s_games = json.loads(M47S_RAW.read_text(encoding="utf-8"))
    m47s_triples = set()
    m47s_succ = set()
    for g in m47s_games:
        z = load_shard_for_audit(g["game_seed"])
        for root in g["roots"]:
            m47s_triples.add((root["observation_hash"],
                              root["visible_history_hash"],
                              root["information_set_hash"]))
            ri = locate_root_index(z, root["step_index"])
            na = int(z["n_actions"][ri])
            for ai in range(na):
                for si in range(4):
                    m47s_succ.add(z["state_hash"][ri, ai, si].decode())
    split_triples["m47s_holdout"] = m47s_triples
    split_succ["m47s_holdout"] = m47s_succ
    split_roots["m47s_holdout"] = len(m47s_triples)

    names = list(split_triples)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            inter = split_triples[names[i]] & split_triples[names[j]]
            if inter:
                raise RuntimeError(
                    f"identity overlap {names[i]} ∩ {names[j]} = {len(inter)}")
            inter_s = split_succ[names[i]] & split_succ[names[j]]
            if inter_s:
                raise RuntimeError(
                    f"successor-hash overlap {names[i]} ∩ {names[j]} = {len(inter_s)}")

    names = list(split_triples)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            inter = split_triples[names[i]] & split_triples[names[j]]
            if inter:
                raise RuntimeError(
                    f"identity overlap {names[i]} ∩ {names[j]} = {len(inter)}")

    expected = {"train": 14336, "internal_test": 2048,
                "validation": 2048, "m47s_holdout": 2048}
    for k, v in expected.items():
        if split_roots[k] != v:
            raise RuntimeError(f"{k}: {split_roots[k]} roots != {v}")
        if len(split_triples[k]) != v:
            raise RuntimeError(f"{k}: {len(split_triples[k])} unique != {v}")

    manifest = {
        "splits": {k: {"games": (v[1] - v[0] + 1) if k in SPLITS else 256,
                       "roots": split_roots[k],
                       "unique_root_identities": len(split_triples[k]),
                       "unique_successor_hashes": len(split_succ[k])}
                   for k, v in list(SPLITS.items()) + [("m47s_holdout", M47S_HOLDOUT)]},
        "pairwise_identity_disjoint": True,
        "pairwise_successor_hash_disjoint": True,
        "m47s_holdout_reused": True,
    }
    return manifest


def load_shard_for_audit(seed: int):
    if 6_600_000 <= seed <= 6_602_047:
        d = CORPUS / "games" / "train"
    elif 6_602_048 <= seed <= 6_602_303:
        d = CORPUS / "games" / "val"
    elif 6_602_304 <= seed <= 6_602_559:
        d = CORPUS / "games" / "test"
    else:
        raise RuntimeError(f"seed {seed} out of corpus")
    return dict(np.load(d / f"seed-{seed}" / "shard.npz", allow_pickle=False))


def locate_root_index(z, step_index: int) -> int:
    for c in range(z["n_actions"].shape[0]):
        if int(z["root_meta"][c][0]) == step_index:
            return c
    raise RuntimeError(f"root step {step_index} not in shard")


def label_sanity_checks(games_by_split):
    """Seed range + budget + label sanity, invoked from audit() so the
    checks actually execute (they were previously unreachable module-level
    code after an unconditional return path)."""
    for split, games in games_by_split.items():
        seeds = sorted(g["game_seed"] for g in games)
        a, b = SPLITS[split]
        if seeds[0] != a or seeds[-1] != b or len(set(seeds)) != len(seeds):
            raise RuntimeError(f"{split}: seed range/duplicates invalid")
        for g in games[:3]:
            for root in g["roots"]:
                bm = {r["max_nodes"]: r for r in root["budgets"]}
                budgets = sorted(bm)
                if budgets != [1, 200, 500, 2000]:
                    raise RuntimeError("budget list invalid")
                for b in (1, 2000):
                    rec = bm[b]
                    if not rec["utilities"] or not rec["optimal_set"]:
                        raise RuntimeError("empty utilities/optimal set")


def main() -> None:
    assert SPLN.exists()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print("M48A label generation (via m47s-residual command, budgets 1/200/500/2000)")
    games_by_split = {}
    for split in SPLITS:
        print(f"[{split}]")
        games_by_split[split] = generate_split(split)
    print("Corpus audit (root-identity disjointness across 4 splits)...")
    manifest = audit(games_by_split)
    mp = OUT_ROOT / "label-manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("AUDIT PASS.")
    print(json.dumps(manifest, indent=2))
    print(f"Manifest: {mp}")


if __name__ == "__main__":
    main()
