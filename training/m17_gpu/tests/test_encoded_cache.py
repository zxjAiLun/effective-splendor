import json
from pathlib import Path

import pytest
import torch

from splendor_gpu.encoded_cache import (
    ENCODER_CONTRACT,
    EncodedCache,
    PackedEncodedDataset,
    build_encoded_cache,
    validate_cache_exact,
)
from splendor_gpu.runtime import EXPECTED_THREAD_ENV, validate_thread_environment
from splendor_gpu.self_play_train import collate
from splendor_gpu.train import file_sha256


GEMS = ("white", "blue", "green", "red", "black", "gold")
ROOT = Path(__file__).resolve().parents[3]


def _zero_gems() -> dict[str, int]:
    return {key: 0 for key in GEMS}


def _example(action: dict, visits: int, game_index: int) -> dict:
    players = [
        {
            "id": 0,
            "tokens": _zero_gems(),
            "bonuses": [0, 0, 0, 0, 0],
            "prestige": 0,
            "reserved_count": 0,
            "public_reserved": [],
        },
        {
            "id": 1,
            "tokens": _zero_gems(),
            "bonuses": [0, 0, 0, 0, 0],
            "prestige": 0,
            "reserved_count": 0,
            "public_reserved": [],
        },
    ]
    observation = {
        "viewer": 0,
        "public": {
            "player_count": 2,
            "players": players,
            "market": [[None, None, None, None], [None, None, None, None], [None, None, None, None]],
            "nobles": [],
            "bank": _zero_gems(),
            "deck_counts": [0, 0, 0],
            "phase": "main",
            "current_player": 0,
            "end_game_triggered": False,
            "turns_remaining_in_final_round": None,
            "consecutive_forced_passes": 0,
        },
        "private": {"reserved": []},
    }
    return {
        "observation": observation,
        "actor": 0,
        "final_ranks": [0, 1],
        "legal_actions": [action],
        "action_stats": [{"action": action, "visits": visits}],
        "game_index": game_index,
    }


def test_cache_round_trip_is_bit_exact_and_packed(tmp_path):
    pass_action = {"type": "pass"}
    take_action = {"type": "take_tokens", "take": {**_zero_gems(), "white": 1}}
    examples = [_example(pass_action, 3, 0), _example(take_action, 7, 1)]
    cache_dir = tmp_path / "cache"

    build_encoded_cache(
        examples,
        {"cards": {}, "nobles": {}},
        cache_dir,
        dataset_file_sha256="a" * 64,
        self_play_hash="b" * 64,
        catalog_hash="c" * 64,
    )
    cache = EncodedCache.load(cache_dir)

    assert cache.manifest["encoder_contract"] == ENCODER_CONTRACT
    assert cache.examples == 2
    assert cache.total_actions == 2
    assert cache.manifest["arrays"]["actions"]["shape"] == [2, 36]
    assert validate_cache_exact(cache, examples, {"cards": {}, "nobles": {}}) == 2

    dataset = PackedEncodedDataset(cache, [1, 0])
    batch = collate([dataset[0], dataset[1]])
    assert batch["entities"].shape == (2, 31, 32)
    assert batch["actions"].shape == (2, 1, 36)
    assert torch.equal(batch["action_mask"], torch.ones((2, 1), dtype=torch.bool))

    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == cache.manifest_sha256


def test_cache_rejects_changed_source_identity(tmp_path):
    example = _example({"type": "pass"}, 1, 0)
    cache_dir = tmp_path / "cache"
    build_encoded_cache(
        [example],
        {"cards": {}, "nobles": {}},
        cache_dir,
        dataset_file_sha256="a" * 64,
        self_play_hash="b" * 64,
        catalog_hash="c" * 64,
    )
    cache = EncodedCache.load(cache_dir)
    with pytest.raises(ValueError, match="source identity mismatch"):
        cache.validate_identity(
            dataset_file_sha256="d" * 64,
            self_play_hash="b" * 64,
            catalog_hash="c" * 64,
            examples=1,
        )


def test_cpu_thread_contract_is_fail_closed():
    assert EXPECTED_THREAD_ENV == {
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "NUMEXPR_NUM_THREADS": "2",
    }
    validate_thread_environment(EXPECTED_THREAD_ENV)
    changed = dict(EXPECTED_THREAD_ENV)
    changed["OMP_NUM_THREADS"] = "14"
    with pytest.raises(RuntimeError, match="explicit CPU thread caps"):
        validate_thread_environment(changed)


def test_runtime_repair_binds_original_scientific_config_without_editing_it():
    repair = json.loads(
        (ROOT / "benchmarks/m28b-runtime-repair-1.json").read_text(encoding="utf-8")
    )
    config_path = ROOT / repair["scientific_config"]["path"]
    assert file_sha256(config_path) == repair["scientific_config"]["sha256"]
    assert repair["scientific_config"]["must_remain_unchanged"] is True
    assert repair["diagnostic"]["scientific_evidence"] is False
    assert repair["encoded_cache"]["full_online_cache_exact_equality_required"] is True
