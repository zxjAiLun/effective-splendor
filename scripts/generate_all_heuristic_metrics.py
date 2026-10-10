import json
from pathlib import Path
import subprocess

ROOT = Path(".")
BATCH_METRICS_BIN = ROOT / "target/eval_target/release/examples/s4_batch_metrics.exe"

def ensure_rotation_metrics(artifact_dir):
    art_path = ROOT / artifact_dir
    manifest_file = art_path / "manifest.json"
    if not manifest_file.exists():
        print(f"Manifest not found: {manifest_file}")
        return
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    rows = manifest["rows"]
    opponents = sorted(list(set(r["opponent"] for r in rows)))

    for opp in opponents:
        for rot in [0, 1]:
            rot_manifest_path = art_path / f"manifest_{opp}_r{rot}.json"
            rot_metrics_path = art_path / f"metrics_{opp}_r{rot}.json"
            if not rot_metrics_path.exists():
                sub_rows = [r for r in rows if r["opponent"] == opp and r["rotation"] == rot]
                sub_manifest = dict(manifest)
                sub_manifest["rows"] = sub_rows
                with open(rot_manifest_path, "w", encoding="utf-8") as f:
                    json.dump(sub_manifest, f, indent=2)
                subprocess.run([str(BATCH_METRICS_BIN), str(rot_manifest_path), str(rot_metrics_path)], check=True)
                print(f"Generated {rot_metrics_path.name} ({len(sub_rows)} games)")

def main():
    for d in ["local-artifacts/s4-heuristic-v029-pilot", "local-artifacts/s4-heuristic-v030-pilot", "local-artifacts/s4-heuristic-v031-pilot"]:
        print(f"Processing {d}...")
        ensure_rotation_metrics(d)
    print("All rotation metrics ready.")

if __name__ == "__main__":
    main()
