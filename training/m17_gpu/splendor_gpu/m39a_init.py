"""Create the cycle-0 M39A checkpoint from the frozen D2-v2 actor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import torch

from .data import catalog_semantic_hash, load_catalog
from .m39a_contract import file_sha256, load_plan, plan_hash
from .m39a_model import build_initial_checkpoint


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize M39A cycle-0 checkpoint")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"output already exists: {args.out}")
    plan = load_plan(args.plan)
    digest = plan_hash(plan)
    catalog_path = Path(plan["catalog"]["path"])
    catalog = load_catalog(catalog_path)
    cat_hash = catalog_semantic_hash(catalog)
    if cat_hash != plan["catalog"]["semantic_hash"]:
        raise ValueError("plan catalog hash mismatch")
    base = Path(plan["initialization"]["checkpoint_path"])
    expected_base_hash = plan["initialization"]["checkpoint_file_sha256"]
    payload = build_initial_checkpoint(
        base_checkpoint=base,
        expected_base_sha256=expected_base_hash,
        plan_hash=digest,
        catalog_hash=cat_hash,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(args.out.name + f".tmp-{os.getpid()}")
    try:
        torch.save(payload, temporary)
        os.replace(temporary, args.out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(
        json.dumps(
            {
                "status": "ok",
                "plan_hash": digest,
                "checkpoint": str(args.out),
                "checkpoint_hash": payload["checkpoint_hash"],
                "checkpoint_file_sha256": file_sha256(args.out),
                "parameter_count": payload["metadata"]["parameter_count"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
