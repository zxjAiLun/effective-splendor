"""Build/verify the immutable local successor-feature cache for CUDA FQI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m49a_train_c3_refresh4 import (  # noqa: E402
    COMPACT_DIR,
    FROZEN_D2_SHA256,
    REPO,
    sha256_file,
)

CACHE_DIR = REPO / "local-artifacts/m49a-cuda-fast-cache-v1"
EXPORTER_EXE = REPO / "local-artifacts/m49a-c3-runtime/splendor-target-builder-cuda-cache.exe"
# Filled only after the exporter is built from a committed source snapshot.
EXPORTER_SOURCE_COMMIT = "3cbaed4e20f7b60fbddcb93305694565379e5fc9"
EXPORTER_SHA256 = "8e1bcd4226bbb05e8fde570a5feabfeff04405bacea51c4a2e9c37f36657aa98"
OBSERVATION_WIDTH = 368
SUFFIX_WIDTH = 60


def input_paths() -> dict[str, Path]:
    return {
        "train/current_x.f32": COMPACT_DIR / "train/current_x.f32",
        "train/step_costs.f32": COMPACT_DIR / "train/step_costs.f32",
        "train/outcomes.u8": COMPACT_DIR / "train/outcomes.u8",
        "train/compact_transitions.jsonl": COMPACT_DIR / "train/compact_transitions.jsonl",
        "val/current_x.f32": COMPACT_DIR / "val/current_x.f32",
        "val/step_costs.f32": COMPACT_DIR / "val/step_costs.f32",
        "val/outcomes.u8": COMPACT_DIR / "val/outcomes.u8",
        "val/compact_transitions.jsonl": COMPACT_DIR / "val/compact_transitions.jsonl",
    }


def snapshot_input_hashes() -> dict[str, str]:
    paths = input_paths()
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing D2 input {name}: {path}")
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    if hashes != FROZEN_D2_SHA256:
        raise RuntimeError("D2 files differ from the fixed clean2-round2 dataset")
    return hashes


def verify_exporter() -> str:
    if "__PIN_" in EXPORTER_SHA256 or "__PIN_" in EXPORTER_SOURCE_COMMIT:
        raise RuntimeError("CUDA cache exporter pins have not been filled after release build")
    if not EXPORTER_EXE.is_file():
        raise FileNotFoundError(f"frozen CUDA cache exporter is missing: {EXPORTER_EXE}")
    actual = sha256_file(EXPORTER_EXE)
    if actual != EXPORTER_SHA256:
        raise RuntimeError(
            f"frozen exporter hash mismatch: expected {EXPORTER_SHA256}, got {actual}"
        )
    return actual


def _validate_split(directory: Path, split: str, transition_count: int) -> dict[str, Any]:
    prefix = directory / "next_obs_prefix.f32"
    suffix = directory / "next_action_suffix.f32"
    offsets_path = directory / "action_offsets.u64"
    expected_prefix_bytes = transition_count * OBSERVATION_WIDTH * 4
    if prefix.stat().st_size != expected_prefix_bytes:
        raise ValueError(f"{split} prefix byte count does not match {transition_count} rows")
    if suffix.stat().st_size % (SUFFIX_WIDTH * 4) != 0:
        raise ValueError(f"{split} suffix file has an invalid feature width")
    expected_offsets_bytes = (transition_count + 1) * 8
    if offsets_path.stat().st_size != expected_offsets_bytes:
        raise ValueError(f"{split} offsets byte count does not match {transition_count} rows")

    offsets = np.fromfile(offsets_path, dtype="<u8")
    if offsets.shape != (transition_count + 1,) or int(offsets[0]) != 0:
        raise ValueError(f"{split} offsets have an invalid shape or first value")
    if np.any(offsets[1:] < offsets[:-1]):
        raise ValueError(f"{split} offsets are not monotone")
    successor_rows = suffix.stat().st_size // (SUFFIX_WIDTH * 4)
    if int(offsets[-1]) != successor_rows:
        raise ValueError(f"{split} final offset does not equal suffix row count")

    outcomes_path = COMPACT_DIR / split / "outcomes.u8"
    outcomes = np.fromfile(outcomes_path, dtype=np.uint8)
    counts = np.diff(offsets)
    if outcomes.shape != (transition_count,):
        raise ValueError(f"{split} outcomes have an invalid row count")
    if not np.array_equal(outcomes == 2, counts > 0):
        raise ValueError(f"{split} Running outcomes and action offsets disagree")

    return {
        "transition_rows": transition_count,
        "running_rows": int(np.count_nonzero(outcomes == 2)),
        "successor_action_rows": int(successor_rows),
        "prefix_width": OBSERVATION_WIDTH,
        "suffix_width": SUFFIX_WIDTH,
        "action_offsets_rows": int(len(offsets)),
        "outputs": {
            prefix.name: {"bytes": prefix.stat().st_size, "sha256": sha256_file(prefix)},
            suffix.name: {"bytes": suffix.stat().st_size, "sha256": sha256_file(suffix)},
            offsets_path.name: {
                "bytes": offsets_path.stat().st_size,
                "sha256": sha256_file(offsets_path),
            },
        },
    }


def verify_existing_cache(input_hashes: dict[str, str], exporter_hash: str) -> dict[str, Any]:
    manifest_path = CACHE_DIR / "cache_manifest.json"
    if not manifest_path.is_file():
        raise FileExistsError(
            f"cache directory exists without a valid manifest; refusing overwrite: {CACHE_DIR}"
        )
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("format") != "m49a-cuda-successor-cache-v1":
        raise ValueError("cache manifest format mismatch")
    if manifest.get("input_sha256") != input_hashes:
        raise ValueError("existing cache was built from different D2 inputs")
    exporter = manifest.get("exporter", {})
    if exporter.get("sha256") != exporter_hash or exporter.get("source_commit") != EXPORTER_SOURCE_COMMIT:
        raise ValueError("existing cache exporter provenance does not match frozen pin")
    expected_rows = {"train": 36674, "val": 2402}
    for split, rows in expected_rows.items():
        actual_split = _validate_split(CACHE_DIR / split, split, rows)
        split_record = manifest.get("splits", {}).get(split, {})
        if actual_split != split_record:
            raise ValueError(f"existing {split} cache outputs differ from the manifest")
    manifest["manifest_sha256"] = sha256_file(manifest_path)
    return manifest


def build_cache() -> dict[str, Any]:
    input_hashes = snapshot_input_hashes()
    exporter_hash = verify_exporter()
    if CACHE_DIR.exists():
        return verify_existing_cache(input_hashes, exporter_hash)

    CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{CACHE_DIR.name}.staging-", dir=CACHE_DIR.parent)
    )
    split_records: dict[str, Any] = {}
    try:
        for split, transition_count in (("train", 36674), ("val", 2402)):
            transitions = COMPACT_DIR / split / "compact_transitions.jsonl"
            out_dir = staging / split
            command = [
                str(EXPORTER_EXE),
                "m49a-export-successor-cache",
                "--transitions",
                str(transitions),
                "--out-dir",
                str(out_dir),
            ]
            print(f"Exporting canonical {split} successor features...", flush=True)
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"{split} feature export failed ({result.returncode}):\n{result.stderr}\n{result.stdout}"
                )
            print(result.stdout.strip(), flush=True)
            split_records[split] = _validate_split(out_dir, split, transition_count)

        final_input_hashes = snapshot_input_hashes()
        if final_input_hashes != input_hashes:
            raise RuntimeError("D2 inputs changed while building the successor feature cache")
        manifest = {
            "format": "m49a-cuda-successor-cache-v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": input_hashes,
            "exporter": {
                "path": str(EXPORTER_EXE.relative_to(REPO)).replace("\\", "/"),
                "sha256": exporter_hash,
                "source_commit": EXPORTER_SOURCE_COMMIT,
                "command": "m49a-export-successor-cache",
            },
            "encoding": {
                "endianness": "little",
                "observation_prefix_width": OBSERVATION_WIDTH,
                "action_delta_horizon_suffix_width": SUFFIX_WIDTH,
                "offset_type": "uint64",
            },
            "splits": split_records,
        }
        manifest_path = staging / "cache_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        if CACHE_DIR.exists():
            raise FileExistsError(f"cache destination appeared concurrently: {CACHE_DIR}")
        staging.rename(CACHE_DIR)
        manifest["manifest_sha256"] = sha256_file(CACHE_DIR / "cache_manifest.json")
        print(f"CUDA feature cache ready: {CACHE_DIR}", flush=True)
        return manifest
    except BaseException:
        print(f"Cache build failed; partial output preserved at {staging}", file=sys.stderr)
        raise


def main() -> None:
    manifest = build_cache()
    for split, record in manifest["splits"].items():
        print(
            f"{split}: {record['transition_rows']} transitions, "
            f"{record['successor_action_rows']} successor rows"
        )


if __name__ == "__main__":
    main()
