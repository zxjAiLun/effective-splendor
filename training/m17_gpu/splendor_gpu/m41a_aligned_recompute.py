"""M41A P0 aligned recompute (read-only): recompute the frozen P0 metric
battery over the FORMAL 3-state rule (25/50/75% quantiles of the
selected seat's acting decisions), from the EXISTING pilot branch
artifacts — no new branch execution.

The pilot's per-state branch directories are keyed by ply, and every
legal action of every selected state was already branched, so dropping
the 90% state is a pure subset selection.
"""

from __future__ import annotations

import collections
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PILOT = Path("local-artifacts/m41a-p0-pilot")
QUANTILES = (0.25, 0.5, 0.75)


def ret(outcome: dict, viewer: int) -> float:
    if outcome["status"] == "completed":
        w = outcome["result"]["winners"]
        if len(w) == 2:
            return 0.0
        return 1.0 if viewer in w else -1.0
    d = outcome["cap_scores"][viewer] - outcome["cap_scores"][1 - viewer]
    return -0.5 + 0.5 * math.tanh(d / 4)


def main() -> None:
    legal_counts = []
    tie_densities = []
    gaps_best_second = []
    gaps_best_d2 = []
    shapes = collections.Counter()
    truncated = 0
    total_branches = 0
    states_total = 0
    states_ge2 = 0

    for gdir in sorted(PILOT.glob("game-*")):
        ordinal = int(gdir.name.split("-")[1])
        seat = ordinal % 2
        replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
        steps = replay["steps"]
        plies = [s["ply"] for s in steps if s["actor"] == seat]
        if not plies:
            continue
        n = len(plies)
        idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in QUANTILES})
        for ply in [plies[i] for i in idxs][:3]:  # at most 3, formal rule
            bdir = gdir / f"branch-ply{ply:04d}"
            if not (bdir / "replay-report.json").is_file():
                continue
            states_total += 1
            vals = []
            for d in sorted(bdir.glob("a*/replay-report.json")):
                if d.parent.name.endswith("-rerun"):
                    continue
                rep = json.load(open(d, encoding="utf-8"))
                vals.append(ret(rep["outcome"], seat))
                if rep["outcome"]["status"] == "truncated":
                    truncated += 1
            h0b = json.load(open(bdir / "replay-report.json", encoding="utf-8"))
            vals.append(ret(h0b["outcome"], seat))
            if h0b["outcome"]["status"] == "truncated":
                truncated += 1
            total_branches += len(vals)
            legal_counts.append(len(vals))
            distinct = sorted(set(vals))
            shapes[tuple(distinct)] += 1
            if len(distinct) >= 2:
                states_ge2 += 1
                best = distinct[-1]
                second = distinct[-2]
                gaps_best_second.append(best - second)
                tie_densities.append(sum(1 for v in vals if v == best) / len(vals))
            gaps_best_d2.append(max(vals) - ret(h0b["outcome"], seat))

    summary = {
        "phase": "P0-aligned-recompute",
        "rule": "3 states/game at 25/50/75% quantiles of the selected seat (ordinal mod 2)",
        "states": states_total,
        "total_branches": total_branches,
        "branches_per_game_mean": total_branches / 32,
        "discrimination": {
            "states_ge2_distinct": states_ge2,
            "fraction": states_ge2 / states_total,
        },
        "value_set_shapes": {str(k): v for k, v in sorted(shapes.items(), key=lambda kv: -kv[1])},
        "legal_set": {
            "mean": statistics.mean(legal_counts),
            "median": statistics.median(legal_counts),
            "min": min(legal_counts),
            "max": max(legal_counts),
        },
        "gaps": {
            "best_vs_second": {str(g): c for g, c in sorted(collections.Counter(gaps_best_second).items())},
            "best_vs_d2": {
                "nonzero": sum(1 for g in gaps_best_d2 if g > 0),
                "total": len(gaps_best_d2),
                "distribution": {str(g): c for g, c in sorted(collections.Counter(gaps_best_d2).items())},
            },
        },
        "tie_density_mean": statistics.mean(tie_densities) if tie_densities else None,
        "truncated_branches": truncated,
        "truncated_fraction": truncated / total_branches,
        "runtime_projection": {
            # p50 from the original pilot's fresh-execution timings (3.6s
            # measured; the aligned rule does not change per-branch cost).
            "branch_p50_s_measured": 3.6,
            "branches_per_100_games": total_branches / 32 * 100,
            "hours_per_100_games_at_p50": total_branches / 32 * 100 * 3.6 / 3600,
        },
    }
    out = PILOT / "p0-aligned-recompute.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
