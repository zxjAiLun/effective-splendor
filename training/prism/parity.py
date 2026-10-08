"""Stream EncodedState JSONL to Python predictions for external Rust parity checks."""

import argparse
import json
from pathlib import Path

import torch

from .export import load_weights
from .io import parse_json
from .model import predict


def predict_jsonl(weights, input_path, output_path, *, expected_catalog_fingerprint):
    """Accept raw EncodedState or {input, seed, ply, actor}; emit one Prediction per line."""
    torch.set_num_threads(2)
    model = load_weights(weights, expected_catalog_fingerprint=expected_catalog_fingerprint)
    count = 0
    # CPU float32 only. Do not accidentally truncate fixtures or previous evidence.
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open("x", encoding="utf-8") as dest:
        for line in source:
            row = parse_json(line)
            if isinstance(row, dict) and "input" in row:
                if set(row) - {"input", "seed", "ply", "actor"}:
                    raise ValueError("unknown parity fixture fields")
                row = row["input"]
            prediction = predict(model, row)
            dest.write(json.dumps(prediction, allow_nan=False, separators=(",", ":")) + "\n")
            count += 1
    if not count:
        raise ValueError("empty parity input")
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--catalog-fingerprint", required=True)
    args = parser.parse_args(argv)
    print(f"predicted {predict_jsonl(args.weights, args.input, args.output, expected_catalog_fingerprint=args.catalog_fingerprint)} states")


if __name__ == "__main__":
    main()
