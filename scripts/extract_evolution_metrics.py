import json
from pathlib import Path

ROOT = Path(".")

def load_json(p):
    with open(ROOT / p, "r", encoding="utf-8") as f:
        return json.load(f)

def get_detailed_stats(version_dir, opp):
    m_path = ROOT / version_dir / f"metrics_{opp}.json"
    if not m_path.exists():
        return None
    with open(m_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    
    # In the batch metrics:
    # seat_p0_first is candidate when candidate was Seat 0
    # seat_p1_second is candidate when candidate was Seat 1
    # Note: in s4_batch_metrics.rs:
    # seat_p0_first holds player 0 metrics across ALL matches (both when candidate was P0 and when opponent was P0)!
    # Wait, let's verify how seat_p0_first is computed in s4_batch_metrics.rs!
    return m

print("Script written.")
