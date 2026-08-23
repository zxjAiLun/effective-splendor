
"""
Teacher / Target Quality Audit for M24-S2 Training Pipeline.

Evaluates M22 raw policy prior, 16-simulation search visit targets, and M07 champion
determinations across thousands of verified positions from M24-S2 self-play dataset.
"""

import json
import math
import subprocess
from pathlib import Path
from collections import defaultdict
import numpy as np

def action_key(act):
    """Serialize action to a stable comparable string."""
    return json.dumps(act, sort_keys=True)

def entropy(probs):
    return -sum(p * math.log(max(p, 1e-12)) for p in probs if p > 0)

def kl_divergence(p, q):
    # KL(p || q)
    return sum(pi * math.log(max(pi, 1e-12) / max(qi, 1e-12)) for pi, qi in zip(p, q) if pi > 0)

def run_audit(num_games=32):
    ds_path = Path("local-artifacts/m24-self-play-s2-v1/self-play.json")
    print(f"Loading dataset {ds_path}...")
    with open(ds_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    games = data["games"][:num_games]
    print(f"Analyzing {len(games)} games with M07 (sample_count=4, depth=1, max_nodes=2000)...")

    tmp_dir = Path("/tmp/m07_full_audit")
    tmp_dir.mkdir(exist_ok=True)

    all_positions = []
    
    for g_idx, g in enumerate(games):
        replay_file = tmp_dir / f"game_{g_idx}.replay.json"
        replay_file.write_text(json.dumps(g["replay"]), encoding="utf-8")
        out_file = tmp_dir / f"game_{g_idx}.analysis.json"
        if out_file.exists():
            out_file.unlink()
        
        cmd = [
            "target/release/splendor",
            "analyze-replay-determinization",
            "--input", str(replay_file),
            "--sample-count", "4",
            "--max-depth-turns", "1",
            "--max-nodes", "2000",
            "--sample-seed", "20260810",
            "--out", str(out_file)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"Error running M07 on game {g_idx}: {res.stderr}"
        
        analysis = json.loads(out_file.read_text(encoding="utf-8"))
        frames = analysis["frames"]
        
        # Get examples for this game
        game_examples = [ex for ex in data["examples"] if ex["game_index"] == g["game_index"]]
        assert len(game_examples) == len(frames), f"Game {g_idx} length mismatch"

        for ex, fr in zip(game_examples, frames):
            # Parse actions and probabilities
            stats = ex["action_stats"]
            legal_actions = [s["action"] for s in stats]
            legal_keys = [action_key(a) for a in legal_actions]
            
            # 1. M22 Prior
            priors = [s["prior_micros"] for s in stats]
            prior_sum = sum(priors)
            p_m22 = [p / prior_sum for p in priors]
            m22_top1_idx = int(np.argmax(p_m22))
            m22_top1_key = legal_keys[m22_top1_idx]
            
            # 2. Search Visits
            visits = [s["visits"] for s in stats]
            visit_sum = sum(visits)
            p_search = [v / visit_sum for v in visits]
            # PyTorch argmax tie-break (first maximum)
            search_top1_idx = int(np.argmax(p_search))
            search_top1_key = legal_keys[search_top1_idx]
            
            # 3. M07 Recommendation
            m07_rec = fr["review_result"]["recommended_action"]
            m07_top1_key = action_key(m07_rec)
            m07_idx = legal_keys.index(m07_top1_key) if m07_top1_key in legal_keys else -1
            
            # 4. Values & Meta
            ply = ex["ply"]
            actor = ex["actor"]
            final_ranks = ex["final_ranks"]
            win = 1.0 if final_ranks[actor] == 0 else 0.0
            
            all_positions.append({
                "game_index": g_idx,
                "ply": ply,
                "actor": actor,
                "legal_count": len(legal_actions),
                "m22_top1": m22_top1_key,
                "search_top1": search_top1_key,
                "m07_top1": m07_top1_key,
                "m22_probs": p_m22,
                "search_probs": p_search,
                "m07_idx": m07_idx,
                "m22_entropy": entropy(p_m22),
                "search_entropy": entropy(p_search),
                "kl_search_m22": kl_divergence(p_search, p_m22),
                "m22_m07_prob": p_m22[m07_idx] if m07_idx >= 0 else 0.0,
                "search_m07_prob": p_search[m07_idx] if m07_idx >= 0 else 0.0,
                "m22_m07_rank": int(np.sum(np.array(p_m22) > p_m22[m07_idx])) + 1 if m07_idx >= 0 else 999,
                "search_m07_rank": int(np.sum(np.array(p_search) > p_search[m07_idx])) + 1 if m07_idx >= 0 else 999,
                "action_type": ex["chosen_action"].get("type", "other"),
                "win": win,
            })

    print(f"Total positions analyzed: {len(all_positions)}")
    return all_positions

def summarize_stratum(positions, label):
    n = len(positions)
    if n == 0:
        return f"=== {label} (N=0) ==="

    m22_search_agree = sum(p["m22_top1"] == p["search_top1"] for p in positions) / n
    search_corrected = 1.0 - m22_search_agree
    
    m22_m07_agree = sum(p["m22_top1"] == p["m07_top1"] for p in positions) / n
    search_m07_agree = sum(p["search_top1"] == p["m07_top1"] for p in positions) / n
    
    # Correction analysis
    # Useful: search != M22 AND search == M07 (search fixed M22's error)
    useful_corr = sum(p["m22_top1"] != p["m07_top1"] and p["search_top1"] == p["m07_top1"] for p in positions) / n
    # Harmful: M22 == M07 AND search != M07 (search broke M22's correct decision)
    harmful_corr = sum(p["m22_top1"] == p["m07_top1"] and p["search_top1"] != p["m07_top1"] for p in positions) / n
    # Neutral correction: search != M22, but neither is M07
    neutral_corr = sum(p["m22_top1"] != p["search_top1"] and p["m22_top1"] != p["m07_top1"] and p["search_top1"] != p["m07_top1"] for p in positions) / n
    
    net_improvement = useful_corr - harmful_corr
    
    # Conditional Useful Rate: given search changed M22, how often did it fix it?
    changed_count = sum(p["m22_top1"] != p["search_top1"] for p in positions)
    cond_useful = (sum(p["m22_top1"] != p["m07_top1"] and p["search_top1"] == p["m07_top1"] for p in positions) / changed_count) if changed_count > 0 else 0.0

    mean_kl = np.mean([p["kl_search_m22"] for p in positions])
    mean_m22_ent = np.mean([p["m22_entropy"] for p in positions])
    mean_search_ent = np.mean([p["search_entropy"] for p in positions])
    
    mean_m22_m07_prob = np.mean([p["m22_m07_prob"] for p in positions])
    mean_search_m07_prob = np.mean([p["search_m07_prob"] for p in positions])
    
    mean_m22_m07_rank = np.mean([p["m22_m07_rank"] for p in positions])
    mean_search_m07_rank = np.mean([p["search_m07_rank"] for p in positions])
    
    win_rate = np.mean([p["win"] for p in positions])
    win_var = np.var([p["win"] for p in positions])

    res = {
        "label": label,
        "n": n,
        "m22_search_agreement": m22_search_agree,
        "search_correction_rate": search_corrected,
        "m22_m07_agreement": m22_m07_agree,
        "search_m07_agreement": search_m07_agree,
        "useful_correction_rate": useful_corr,
        "harmful_correction_rate": harmful_corr,
        "neutral_correction_rate": neutral_corr,
        "net_improvement": net_improvement,
        "cond_useful_rate": cond_useful,
        "mean_kl_search_m22": mean_kl,
        "mean_m22_entropy": mean_m22_ent,
        "mean_search_entropy": mean_search_ent,
        "mean_m22_m07_prob": mean_m22_m07_prob,
        "mean_search_m07_prob": mean_search_m07_prob,
        "mean_m22_m07_rank": mean_m22_m07_rank,
        "mean_search_m07_rank": mean_search_m07_rank,
        "win_variance": win_var,
    }
    return res

if __name__ == "__main__":
    positions = run_audit(num_games=32)
    
    overall = summarize_stratum(positions, "ALL POSITIONS (Overall)")
    
    # Stratify by Phase
    early = summarize_stratum([p for p in positions if p["ply"] < 16], "Early Game (Ply 0-15)")
    mid = summarize_stratum([p for p in positions if 16 <= p["ply"] < 36], "Mid Game (Ply 16-35)")
    late = summarize_stratum([p for p in positions if p["ply"] >= 36], "Late Game (Ply 36+)")
    
    # Stratify by Branching Factor (Legal Actions Count)
    low_legal = summarize_stratum([p for p in positions if p["legal_count"] <= 15], "Low Legal Actions (<= 15)")
    med_legal = summarize_stratum([p for p in positions if 16 <= p["legal_count"] <= 30], "Medium Legal Actions (16-30)")
    high_legal = summarize_stratum([p for p in positions if p["legal_count"] > 30], "High Legal Actions (> 30)")
    
    # Stratify by Search Entropy (Agreement certainty)
    low_ent = summarize_stratum([p for p in positions if p["search_entropy"] < 1.0], "Low Search Entropy (< 1.0 nats)")
    high_ent = summarize_stratum([p for p in positions if p["search_entropy"] >= 1.0], "High Search Entropy (>= 1.0 nats)")

    # Stratify by Action Type
    tokens = summarize_stratum([p for p in positions if p["action_type"] == "take_tokens"], "Action: Take Tokens")
    buy = summarize_stratum([p for p in positions if "purchase" in p["action_type"] or "buy" in p["action_type"]], "Action: Purchase Card")
    reserve = summarize_stratum([p for p in positions if "reserve" in p["action_type"]], "Action: Reserve Card")

    report = {
        "overall": overall,
        "by_phase": {"early": early, "mid": mid, "late": late},
        "by_legal_count": {"low": low_legal, "med": med_legal, "high": high_legal},
        "by_search_entropy": {"low": low_ent, "high": high_ent},
        "by_action_type": {"take_tokens": tokens, "purchase": buy, "reserve": reserve},
    }
    
    out_json = Path("local-artifacts/m24_s2_teacher_target_audit.json")
    out_json.parent.mkdir(exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved to {out_json}")
