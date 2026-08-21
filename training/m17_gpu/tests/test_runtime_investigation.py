import json
from pathlib import Path

import pytest

from splendor_gpu.m28b_runtime_investigation import (
    ThermalSafetyAbort,
    maximum_temperature_c,
    process_thread_count,
    require_thermal_headroom,
)


ROOT = Path(__file__).resolve().parents[3]


def test_maximum_temperature_is_fail_closed_for_numeric_readings():
    readings = [
        {"label": "core", "celsius": 71.5},
        {"label": "package", "celsius": 89.9},
    ]
    assert maximum_temperature_c(readings) == pytest.approx(89.9)


def test_thermal_abort_uses_at_or_above_threshold(monkeypatch):
    monkeypatch.setattr(
        "splendor_gpu.m28b_runtime_investigation.cpu_temperatures_c",
        lambda: [{"label": "package", "celsius": 90.0}],
    )
    with pytest.raises(ThermalSafetyAbort, match="thermal safety abort"):
        require_thermal_headroom("test")


def test_process_thread_count_is_observable():
    value = process_thread_count()
    assert value is None or value >= 1


def test_investigation_contract_is_read_only_and_binds_cache_identity():
    contract = json.loads(
        (ROOT / "benchmarks/m28b-runtime-investigation-2a.json").read_text(encoding="utf-8")
    )
    assert contract["runtime"]["system_power_policy_mutation"] is False
    assert contract["runtime"]["linux_governor_mutation"] is False
    assert contract["runtime"]["turbo_mutation"] is False
    assert contract["runtime"]["gpu_power_limit_mutation"] is False
    assert contract["cache"]["dataset_raw_file_is_not_reread"] is True
    assert contract["profile"]["checkpoint_written"] is False
    assert contract["profile"]["offline_result_written"] is False
    assert contract["host_safety"]["cpu_temperature_limit_celsius"] == 90.0
