"""Targeted unit tests for M28B Compute Repair 2 machinery."""

import copy
import json
from pathlib import Path
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from splendor_gpu.encoding import ACTION_FEATURES, ENTITY_FEATURES, GLOBAL_FEATURES, ENTITY_SLOTS
from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset, collate_packed
from splendor_gpu.model import ContextualInteractionBlock, ContextualEntityMixerPolicyValue, ModelSpec, build_model
from splendor_gpu.self_play_train import evaluate
from splendor_gpu.interaction_train import (
    BackgroundThermalGuard,
    PHYSICAL_MICROBATCH_SIZE,
    ThermalSafetyAbort,
    ThermalTelemetryUnavailable,
    _loader,
    iter_physical_microbatches,
    sensor_threshold,
    thermal_pacing_bounds,
    verify_and_reevaluate_control,
    wait_for_soft_thermal_envelope,
    CPU_THERMAL_LIMIT_C,
    GPU_THERMAL_LIMIT_C,
    NVME_THERMAL_LIMIT_C,
    PLATFORM_THERMAL_LIMIT_C,
    VERIFIED_CONTROL_REPORT_SHA256,
    VERIFIED_CONTROL_CHECKPOINT_SHA256,
    VERIFIED_CONTROL_SEMANTIC_HASH,
)
from splendor_gpu.train import file_sha256


def test_vectorized_batch_loader_exact_equality():
    cache_path = Path("local-artifacts/m28b-encoded-cache-v1")
    if not cache_path.exists():
        pytest.skip("m28b encoded cache not found locally")

    cache = EncodedCache.load(cache_path)
    indices = [0, 5, 12, 19, 45, 128, 256, 512, 1024]

    # Sample-by-sample collate
    samples = [cache.sample(i) for i in indices]
    batch_ref = collate_packed(samples)

    # Vectorized 1-shot batch
    batch_fast = cache.batch(indices)

    assert set(batch_ref.keys()) == set(batch_fast.keys())
    for k in batch_ref:
        assert torch.equal(batch_ref[k], batch_fast[k]), f"Tensor mismatch for key '{k}'"


def test_fast_loader_shuffle_order_exact_match():
    cache_path = Path("local-artifacts/m28b-encoded-cache-v1")
    if not cache_path.exists():
        pytest.skip("m28b encoded cache not found locally")

    cache = EncodedCache.load(cache_path)
    subset_indices = list(range(0, 500, 2))  # 250 samples
    dataset = PackedEncodedDataset(cache, subset_indices)

    batch_size = 64
    seed = 280229
    device = torch.device("cpu")

    # Reference PyTorch DataLoader
    gen = torch.Generator().manual_seed(seed)
    loader_ref = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=gen,
        num_workers=0,
        collate_fn=collate_packed,
    )

    # Vectorized fast loader
    loader_fast = _loader(dataset, batch_size=batch_size, shuffle=True, seed=seed, device=device)

    batches_ref = list(loader_ref)
    batches_fast = list(loader_fast)

    assert len(batches_ref) == len(batches_fast)
    for b_idx, (br, bf) in enumerate(zip(batches_ref, batches_fast)):
        for k in br:
            assert torch.equal(br[k], bf[k]), f"Batch {b_idx} key {k} mismatch"


def test_physical_microbatch_gradient_matches_logical_batch():
    torch.manual_seed(280229)
    samples = []
    for index in range(7):
        action_count = 3 + index
        samples.append({
            "entities": torch.randn(ENTITY_SLOTS, ENTITY_FEATURES),
            "entity_mask": torch.rand(ENTITY_SLOTS) > 0.2,
            "global_features": torch.randn(GLOBAL_FEATURES),
            "actions": torch.randn(action_count, ACTION_FEATURES),
            "policy_target": torch.softmax(torch.randn(action_count), dim=-1),
            "value_target": torch.softmax(torch.randn(2), dim=-1),
        })
    logical_batch = collate_packed(samples)
    spec = ModelSpec("contextual_entity_mixer", 32, 1, 0.0, 1)
    full_model = build_model(spec)
    micro_model = copy.deepcopy(full_model)

    def loss_for(model, batch):
        logits, values = model.forward_packed(
            batch["entities"], batch["entity_mask"], batch["global_features"],
            batch["actions"], batch["action_offsets"],
        )
        from splendor_gpu.self_play_train import packed_policy_loss
        policy = packed_policy_loss(logits, batch["policy_target"], batch["action_offsets"])
        value = F.mse_loss(values, batch["value_target"])
        return policy + 0.5 * value

    loss_for(full_model, logical_batch).backward()
    logical_count = len(samples)
    reconstructed = []
    for microbatch in iter_physical_microbatches(logical_batch, 3):
        micro_count = int(microbatch["entities"].shape[0])
        (loss_for(micro_model, microbatch) * (micro_count / logical_count)).backward()
        reconstructed.append(microbatch)

    assert [int(batch["entities"].shape[0]) for batch in reconstructed] == [3, 3, 1]
    for (name_full, param_full), (name_micro, param_micro) in zip(
        full_model.named_parameters(), micro_model.named_parameters(), strict=True
    ):
        assert name_full == name_micro
        assert param_full.grad is not None and param_micro.grad is not None
        assert torch.allclose(param_full.grad, param_micro.grad, rtol=2e-5, atol=2e-6), name_full


def test_soft_thermal_pacing_hysteresis():
    gpu = {"source": "nvml:gpu_0", "label": "NVIDIA GPU", "celsius": 86.0, "hard_limit_c": 90.0}
    assert thermal_pacing_bounds(gpu) == (85.0, 78.0)
    sen3 = {"source": "thermal_zone2", "label": "SEN3", "celsius": 75.0, "firmware_crit": 80.05}
    trigger, resume = thermal_pacing_bounds(sen3)
    assert trigger == pytest.approx(74.05)
    assert resume == pytest.approx(68.05)

    class FakeGuard:
        device = torch.device("cpu")

        @staticmethod
        def check():
            return None

    samples = iter([
        [gpu],
        [{**gpu, "celsius": 82.0}],
        [{**gpu, "celsius": 77.0}],
    ])
    sleeps = []
    stats = {"pause_count": 0, "total_pause_seconds": 0.0, "max_pause_seconds": 0.0}
    wait_for_soft_thermal_envelope(
        FakeGuard(),  # type: ignore[arg-type]
        stats,
        sample_fn=lambda: next(samples),
        sleep_fn=sleeps.append,
    )
    assert stats["pause_count"] == 1
    assert sleeps == [1.0]
    assert PHYSICAL_MICROBATCH_SIZE == 32

    with pytest.raises(ThermalSafetyAbort, match="NVIDIA GPU.*90.0°C >= limit 90.0°C"):
        wait_for_soft_thermal_envelope(
            FakeGuard(),  # type: ignore[arg-type]
            {},
            sample_fn=lambda: [{**gpu, "celsius": 90.0}],
            sleep_fn=lambda _: None,
        )


def test_bmm_aggregation_numerical_equivalence_and_parameter_gradients():
    """Verify BMM aggregation against legacy 4D tensor across inputs and all model parameters."""
    torch.manual_seed(42)
    B, N, H = 8, 31, 192

    class LegacyInteractionBlock(nn.Module):
        def __init__(self, width: int):
            super().__init__()
            self.norm = nn.LayerNorm(width)
            self.query = nn.Linear(width, width)
            self.key = nn.Linear(width, width)
            self.value = nn.Linear(width, width)
            self.pair = nn.Sequential(
                nn.Linear(width * 3, width),
                nn.GELU(),
                nn.Linear(width, 1),
            )
            self.residual = nn.Sequential(
                nn.Linear(width * 3, width),
                nn.GELU(),
                nn.Dropout(0.0),
                nn.Linear(width, width),
                nn.Dropout(0.0),
            )

        def forward(self, entities, mask, global_context):
            normalized = self.norm(entities)
            queries = self.query(normalized)
            keys = self.key(normalized)
            values = self.value(normalized)

            w = self.pair[0].weight
            b = self.pair[0].bias
            h = entities.shape[-1]
            proj_q = F.linear(queries, w[:, 0:h])
            proj_k = F.linear(keys, w[:, h : 2 * h])
            proj_p = F.linear(queries.unsqueeze(2) * keys.unsqueeze(1), w[:, 2 * h : 3 * h], b)
            h_pair = proj_q.unsqueeze(2) + proj_k.unsqueeze(1) + proj_p
            interaction = torch.sigmoid(self.pair[2](self.pair[1](h_pair)).squeeze(-1))

            entity_count = entities.shape[1]
            not_self = ~torch.eye(entity_count, dtype=torch.bool, device=entities.device).unsqueeze(0)
            pair_mask = mask.unsqueeze(1) & mask.unsqueeze(2) & not_self
            interaction = interaction.masked_fill(~pair_mask, 0.0)
            denominator = interaction.sum(dim=-1, keepdim=True).clamp_min(1e-6)

            # Unoptimized 4D intermediate tensor allocation
            context = (interaction.unsqueeze(-1) * values.unsqueeze(1)).sum(dim=2) / denominator
            context = context.masked_fill(~mask.unsqueeze(-1), 0.0)

            expanded_global = global_context.unsqueeze(1).expand(-1, entity_count, -1)
            updated = entities + self.residual(torch.cat((entities, context, expanded_global), dim=-1))
            updated = updated.masked_fill(~mask.unsqueeze(-1), 0.0)
            return updated, context

    block_legacy = LegacyInteractionBlock(H)
    block_new = ContextualInteractionBlock(H, dropout=0.0)

    # Initialize with identical weights
    block_new.load_state_dict(block_legacy.state_dict(), strict=False)

    entities_legacy = torch.randn(B, N, H, requires_grad=True)
    entities_new = entities_legacy.clone().detach().requires_grad_(True)
    mask = torch.rand(B, N) > 0.2
    global_ctx_legacy = torch.randn(B, H, requires_grad=True)
    global_ctx_new = global_ctx_legacy.clone().detach().requires_grad_(True)

    # Forward
    out_legacy, ctx_legacy = block_legacy(entities_legacy, mask, global_ctx_legacy)
    out_new, ctx_new = block_new(entities_new, mask, global_ctx_new)

    max_out_diff = (out_new - out_legacy).abs().max().item()
    max_ctx_diff = (ctx_new - ctx_legacy).abs().max().item()
    assert max_out_diff < 1e-5, f"forward output diff {max_out_diff} exceeds 1e-5"
    assert max_ctx_diff < 1e-5, f"forward context diff {max_ctx_diff} exceeds 1e-5"

    # Backward
    loss_legacy = (out_legacy * 2.0).sum() + ctx_legacy.sum()
    loss_new = (out_new * 2.0).sum() + ctx_new.sum()
    loss_legacy.backward()
    loss_new.backward()

    # Check input gradients
    max_in_grad_diff = (entities_new.grad - entities_legacy.grad).abs().max().item()
    max_gctx_grad_diff = (global_ctx_new.grad - global_ctx_legacy.grad).abs().max().item()
    assert max_in_grad_diff < 1e-5, f"input grad diff {max_in_grad_diff} exceeds 1e-5"
    assert max_gctx_grad_diff < 1e-5, f"global ctx grad diff {max_gctx_grad_diff} exceeds 1e-5"

    # Check parameter-by-parameter gradients
    for (pname_legacy, p_legacy), (pname_new, p_new) in zip(block_legacy.named_parameters(), block_new.named_parameters()):
        assert pname_legacy == pname_new
        assert p_legacy.grad is not None and p_new.grad is not None
        param_grad_diff = (p_new.grad - p_legacy.grad).abs().max().item()
        assert param_grad_diff < 5e-5, f"parameter {pname_new} grad diff {param_grad_diff} exceeds 5e-5"


def test_evaluator_numerical_equivalence_to_legacy_cpu():
    """Verify GPU segmented evaluator against legacy CPU evaluator across packed multi-batch inputs."""
    torch.manual_seed(777)
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    # Legacy CPU evaluator function
    def evaluate_legacy(m, loader):
        m.eval()
        cross_entropy = value_mse = visit_top1 = examples = 0.0
        with torch.no_grad():
            for batch in loader:
                if "action_offsets" in batch:
                    logits, values = m.forward_packed(
                        batch["entities"], batch["entity_mask"], batch["global_features"],
                        batch["actions"], batch["action_offsets"],
                    )
                    offsets = batch["action_offsets"]
                    counts = offsets[1:] - offsets[:-1]
                    batch_size = counts.shape[0]
                    segment_ids = torch.repeat_interleave(torch.arange(batch_size, device=logits.device), counts)
                    max_per_seg = torch.full((batch_size,), -torch.inf, dtype=logits.dtype, device=logits.device)
                    max_per_seg.scatter_reduce_(0, segment_ids, logits, reduce="amax")
                    shifted_exp = torch.exp(logits - max_per_seg[segment_ids])
                    sum_exp_per_seg = torch.zeros(batch_size, dtype=logits.dtype, device=logits.device)
                    sum_exp_per_seg.scatter_add_(0, segment_ids, shifted_exp)
                    lse_per_seg = max_per_seg + torch.log(sum_exp_per_seg)
                    log_probs = logits - lse_per_seg[segment_ids]
                    prod = batch["policy_target"] * log_probs
                    loss_per_seg = torch.zeros(batch_size, dtype=logits.dtype, device=logits.device)
                    loss_per_seg.scatter_add_(0, segment_ids, -prod)
                    cross_entropy += loss_per_seg.sum().item()

                    splits_l = torch.tensor_split(logits.cpu(), offsets[1:-1].cpu())
                    splits_t = torch.tensor_split(batch["policy_target"].cpu(), offsets[1:-1].cpu())
                    for sl, st in zip(splits_l, splits_t):
                        if sl.argmax(dim=-1).item() == st.argmax(dim=-1).item():
                            visit_top1 += 1.0
                    count = batch_size
                else:
                    logits, values = m(
                        batch["entities"], batch["entity_mask"], batch["global_features"],
                        batch["actions"], batch["action_mask"],
                    )
                    count = logits.shape[0]
                    cross_entropy += (-(batch["policy_target"] * torch.log_softmax(logits, dim=-1)).sum(dim=-1)).sum().item()
                    visit_top1 += batch["policy_target"].argmax(dim=-1).eq(logits.argmax(dim=-1)).sum().item()

                value_mse += F.mse_loss(values, batch["value_target"], reduction="sum").item()
                examples += count
        return {
            "examples": int(examples),
            "policy_cross_entropy": cross_entropy / examples,
            "visit_top1": visit_top1 / examples,
            "value_mse": value_mse / (examples * 2.0),
        }

    # Generate synthetic packed samples with variable action counts and ties
    samples = []
    for i in range(32):
        k = torch.randint(5, 45, (1,)).item()
        p_target = torch.softmax(torch.randn(k), dim=-1)
        # Create intentional first-tie scenarios in some samples
        if i % 4 == 0:
            p_target[0] = 0.5
            p_target[min(1, k - 1)] = 0.5

        samples.append({
            "entities": torch.randn(31, ENTITY_FEATURES),
            "entity_mask": torch.rand(31) > 0.2,
            "global_features": torch.randn(GLOBAL_FEATURES),
            "actions": torch.randn(k, ACTION_FEATURES),
            "policy_target": p_target,
            "value_target": torch.softmax(torch.randn(2), dim=-1),
        })

    loader = DataLoader(samples, batch_size=8, shuffle=False, collate_fn=collate_packed)

    metrics_legacy = evaluate_legacy(model, loader)
    metrics_new = evaluate(model, loader, torch.device("cpu"))

    assert metrics_legacy["examples"] == metrics_new["examples"] == 32
    assert metrics_legacy["visit_top1"] == metrics_new["visit_top1"], "visit_top1 must match 100% exactly"
    assert abs(metrics_legacy["policy_cross_entropy"] - metrics_new["policy_cross_entropy"]) < 1e-6
    assert abs(metrics_legacy["value_mse"] - metrics_new["value_mse"]) < 1e-6


def test_sensor_specific_thresholds_and_firmware_trip_points():
    assert sensor_threshold("coretemp:Package id 0") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("coretemp:Core 8") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("x86_pkg_temp") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("TCPU") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("TCPU_PCI") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("nvme:Composite") == NVME_THERMAL_LIMIT_C
    assert sensor_threshold("SEN3") == PLATFORM_THERMAL_LIMIT_C
    assert sensor_threshold("acpitz") == PLATFORM_THERMAL_LIMIT_C

    # Firmware critical: SEN3 firmware_crit=80.05, firmware_hot=75.05 -> limit must be min(85, 80.05-2) = 78.05
    sen3_sensor = {"label": "SEN3", "firmware_crit": 80.05, "firmware_hot": 75.05}
    assert sensor_threshold(sen3_sensor) == 78.05

    # NVMe firmware critical: crit=84.85 -> min(80.0, 84.85-2.0) = 80.0
    nvme_sensor = {"label": "nvme:Composite", "firmware_crit": 84.85, "firmware_hot": 82.85}
    assert sensor_threshold(nvme_sensor) == 80.0


def test_thermal_guard_sensor_specific_abort(monkeypatch):
    # 1. CPU sensor exceeds 95.0
    readings = [{"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 96.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings)
    guard = BackgroundThermalGuard(device=torch.device("cpu"), interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'coretemp:Package id 0' .* measured 96.0°C >= limit 95.0°C"):
        guard.start()

    # 2. SEN3 exceeds firmware critical - 2.0 (78.05C)
    readings_sen3 = [{"source": "/sys/class/thermal/thermal_zone2/temp", "label": "SEN3", "celsius": 79.0, "firmware_crit": 80.05}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings_sen3)
    guard_sen3 = BackgroundThermalGuard(device=torch.device("cpu"), interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'SEN3' .* measured 79.0°C >= limit 78.0°C"):
        guard_sen3.start()


def test_control_verification_immutability_and_fail_closed(tmp_path, monkeypatch):
    # Mock thermal readings during CPU test evaluation to avoid live host ambient spikes
    safe_readings = [
        {"source": "/sys/class/thermal/thermal_zone0/temp", "label": "acpitz", "celsius": 30.0},
        {"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 50.0},
    ]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: safe_readings)
    control_orig_dir = Path("local-artifacts/m28b-contextual-entity-interaction-v1-rerun-compute-repair/control")
    if not control_orig_dir.exists():
        pytest.skip("local control artifact not found")

    report_orig_file = control_orig_dir / "training-report.json"
    ckpt_orig_file = control_orig_dir / "checkpoint.pt"

    # Assert immutable SHA of original control files
    assert file_sha256(report_orig_file) == VERIFIED_CONTROL_REPORT_SHA256
    assert file_sha256(ckpt_orig_file) == VERIFIED_CONTROL_CHECKPOINT_SHA256

    # Test verify_and_reevaluate_control on valid directory does NOT mutate training-report.json
    from splendor_gpu.data import load_catalog
    from splendor_gpu.interaction_train import validate_dataset, split_m28b_indices

    cache = EncodedCache.load(Path("local-artifacts/m28b-encoded-cache-v1"))
    config = json.loads(Path("benchmarks/m28b-contextual-entity-interaction-v1.config.json").read_text(encoding="utf-8"))
    catalog = load_catalog(Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))
    payload, actual_self_play_hash, dataset_file_sha256 = validate_dataset(
        Path("local-artifacts/m24-self-play-s2-v1/self-play.json"), config
    )
    train_indices, validation_indices, reference_indices = split_m28b_indices(payload, config)

    # Set up clean test directory with only control/ present
    clean_test_dir = tmp_path / "clean_test_out"
    clean_test_dir.mkdir()
    test_control_dir = clean_test_dir / "control"
    test_control_dir.mkdir()
    (test_control_dir / "training-report.json").write_text(report_orig_file.read_text(encoding="utf-8"), encoding="utf-8")
    (test_control_dir / "checkpoint.pt").write_bytes(ckpt_orig_file.read_bytes())

    report = verify_and_reevaluate_control(
        config["models"][0],
        train_indices,
        validation_indices,
        reference_indices,
        cache,
        catalog,
        config,
        actual_self_play_hash,
        dataset_file_sha256,
        clean_test_dir,
        torch.device("cpu"),
    )

    # Assert report file on disk was NOT mutated
    assert file_sha256(report_orig_file) == VERIFIED_CONTROL_REPORT_SHA256
    assert report["original_report_sha256"] == VERIFIED_CONTROL_REPORT_SHA256
    assert report["evaluator_reassessed"] is True

    # Test fail-closed if candidate/ exists in output directory
    fake_out_dir = tmp_path / "fake_out"
    fake_out_dir.mkdir()
    (fake_out_dir / "control").mkdir()
    (fake_out_dir / "candidate").mkdir()
    with pytest.raises(RuntimeError, match="fail-closed: candidate directory already exists"):
        verify_and_reevaluate_control(
            config["models"][0], [], [], [], cache, catalog, config,
            actual_self_play_hash, dataset_file_sha256, fake_out_dir, torch.device("cpu")
        )
    # Test fail-closed if summary.json exists in output directory
    fake_out_dir2 = tmp_path / "fake_out2"
    fake_out_dir2.mkdir()
    (fake_out_dir2 / "control").mkdir()
    (fake_out_dir2 / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="fail-closed: summary.json already exists"):
        verify_and_reevaluate_control(
            config["models"][0], [], [], [], cache, catalog, config,
            actual_self_play_hash, dataset_file_sha256, fake_out_dir2, torch.device("cpu")
        )

    # Test fail-closed if unexpected file exists in output directory
    fake_out_dir3 = tmp_path / "fake_out3"
    fake_out_dir3.mkdir()
    (fake_out_dir3 / "control").mkdir()
    (fake_out_dir3 / "unexpected.txt").write_text("test", encoding="utf-8")
    (fake_out_dir3 / "control" / "training-report.json").write_text("{}", encoding="utf-8")
    (fake_out_dir3 / "control" / "checkpoint.pt").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="fail-closed: unexpected entry in output directory"):
        verify_and_reevaluate_control(
            config["models"][0], [], [], [], cache, catalog, config,
            actual_self_play_hash, dataset_file_sha256, fake_out_dir3, torch.device("cpu")
        )
