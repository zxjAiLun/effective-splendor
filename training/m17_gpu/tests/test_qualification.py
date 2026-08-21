"""Tests for M28B qualification runner."""

from pathlib import Path
import json
import pytest

from splendor_gpu.m28b_qualification import (
    QUALIFICATION_FORMAT,
    QUALIFICATION_VERSION,
    maximum_temperature_c,
    NvmlCollector,
    ProcessTelemetryReader,
    read_active_core_frequencies,
    validate_qualification_contract,
)
from splendor_gpu.encoded_cache import EncodedCache

ROOT = Path(__file__).resolve().parents[3]


def test_qualification_contract_validation():
    contract_p = ROOT / "benchmarks/m28b-qualification-2b.json"
    config_p = ROOT / "benchmarks/m28b-contextual-entity-interaction-v1.config.json"
    cache_p = ROOT / "local-artifacts/m28b-encoded-cache-v1"
    contract = json.loads(contract_p.read_text(encoding="utf-8"))
    config = json.loads(config_p.read_text(encoding="utf-8"))
    cache = EncodedCache.load(cache_p)

    validate_qualification_contract(contract, config, config_p, cache)


def test_telemetry_readers():
    # Process reader
    proc = ProcessTelemetryReader()
    stat, top = proc.sample_process_and_threads(100.0)
    assert "rss_kb" in stat
    assert "voluntary_ctx_switches" in stat
    assert isinstance(top, list)

    # Core frequencies
    freqs = read_active_core_frequencies()
    if freqs:
        assert "min_mhz" in freqs
        assert "max_mhz" in freqs

    # NVML collector
    nvml = NvmlCollector()
    if nvml.is_available:
        sample = nvml.sample()
        assert sample is not None
        assert "gpu_temp_celsius" in sample
        assert "gpu_power_watts" in sample
        nvml.close()
