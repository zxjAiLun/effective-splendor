"""Generate/verify the public card/noble catalog snapshot from canonical Rust tables."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "crates/splendor-catalog/src/cards.rs"
NOBLES = ROOT / "crates/splendor-catalog/src/nobles.rs"
OUTPUT = Path(__file__).with_name("catalog.json")
CARD = re.compile(r"\bc\((\d+),\s*(One|Two|Three),\s*(White|Blue|Green|Red|Black),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)")
NOBLE = re.compile(r"\bnoble\((\d+),\s*req\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)\)")


def catalog() -> dict:
    cards = []
    for match in CARD.finditer(CARDS.read_text(encoding="utf-8")):
        i, tier, bonus, prestige, *cost = match.groups()
        cards.append(dict(id=int(i), tier=tier, bonus=bonus.lower(), prestige=int(prestige), cost=list(map(int, cost))))
    nobles = []
    for match in NOBLE.finditer(NOBLES.read_text(encoding="utf-8")):
        i, *requirements = match.groups()
        nobles.append(dict(id=int(i), prestige=3, requirements=list(map(int, requirements))))
    if [c["id"] for c in cards] != list(range(90)) or [n["id"] for n in nobles] != list(range(10)):
        raise ValueError("canonical catalog parse failed; update generator for changed Rust tables")
    return {"catalog_version": "0.1.0", "cards": cards, "nobles": nobles}


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(catalog(), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"generated {OUTPUT} (90 cards, 10 nobles)")
