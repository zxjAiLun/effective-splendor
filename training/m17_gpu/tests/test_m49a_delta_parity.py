"""Cross-language parity tests verifying Python m25_delta_v2 matches the shared m49a_delta_parity_v1.json fixture."""
import json
import pytest
from pathlib import Path
from splendor_gpu.data import load_catalog
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2

def test_shared_m49a_delta_parity_fixture():
    fixture_path = Path("crates/splendor-learning/tests/fixtures/m49a_delta_parity_v1.json")
    assert fixture_path.is_file(), f"missing fixture at {fixture_path}"
    
    cat_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    catalog = load_catalog(cat_path)

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["format"] == "effective-splendor-m49a-delta-parity-fixture-v1"
    assert fixture["version"] == 1
    assert len(fixture["cases"]) >= 8

    for c in fixture["cases"]:
        case_id = c["id"]
        obs = c["observation"]
        action = c["action"]
        expected = c["expected_delta_23"]

        actual = encode_action_delta_v2(obs, action, catalog)
        assert len(actual) == 23, f"case {case_id} produced length {len(actual)}"

        for i, (a, e) in enumerate(zip(actual, expected)):
            assert a == pytest.approx(e, abs=1e-5), (
                f"Python mismatch on case '{case_id}' at index {i}: actual {a}, expected {e}"
            )
