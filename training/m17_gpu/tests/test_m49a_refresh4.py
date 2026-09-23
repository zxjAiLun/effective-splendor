"""C3 hard-target refresh-granularity contract tests."""

import json

import numpy as np
import torch

from splendor_gpu import m49a_trainer as T
import m49a_train_c3_refresh4 as C3


def test_wrapper_process_status_persists_exit_code_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(C3, "RUN_DIR", tmp_path)
    monkeypatch.setattr(C3, "RUN_ID", "test-c3-run")
    monkeypatch.setattr(C3, "_RUN_STATUS_ENABLED", True)
    monkeypatch.setattr(C3, "_RUN_STARTED_AT", "2026-09-23T00:00:00+00:00")

    C3._write_process_status("completed", 0)

    with open(tmp_path / "process-status.json", encoding="utf-8") as f:
        status = json.load(f)
    assert status["run_id"] == "test-c3-run"
    assert status["state"] == "completed"
    assert status["exit_code"] == 0
    assert status["started_at_utc"] == "2026-09-23T00:00:00+00:00"
    assert not (tmp_path / "process-status.json.tmp").exists()


def _tiny_inputs(tmp_path, rows=16):
    paths = {}
    values = np.linspace(-0.5, 0.5, rows * 428, dtype=np.float32).reshape(rows, 428)
    for split in ("train", "val"):
        x_path = tmp_path / f"{split}_x.f32"
        values.tofile(x_path)
        transitions_path = tmp_path / f"{split}_transitions.jsonl"
        transitions_path.write_text("", encoding="utf-8")
        paths[split] = (x_path, transitions_path)
    return paths


def _run_tiny(paths, *, refresh_epochs=None, checkpoint_dir=None):
    return T.train_fqi_streaming(
        train_x_path=paths["train"][0],
        train_transitions_path=paths["train"][1],
        val_x_path=paths["val"][0],
        val_transitions_path=paths["val"][1],
        device=torch.device("cpu"),
        epochs_per_fqi=8,
        fqi_iterations=2,
        batch_size=8,
        seed=49000001,
        checkpoint_dir=checkpoint_dir,
        checkpoint_every=1 if checkpoint_dir else 0,
        target_update="hard",
        hard_target_refresh_epochs=refresh_epochs,
    )


def test_refresh_interval_rejects_bad_values_before_dataset_io(tmp_path):
    dummy = tmp_path / "does-not-exist"
    for invalid in (0, -1, 3, 9):
        try:
            T.train_fqi_streaming(
                dummy, dummy, dummy, dummy,
                device=torch.device("cpu"),
                epochs_per_fqi=8,
                hard_target_refresh_epochs=invalid,
            )
            raise AssertionError(f"hard_target_refresh_epochs={invalid} accepted")
        except ValueError:
            pass

    try:
        T.train_fqi_streaming(
            dummy, dummy, dummy, dummy,
            device=torch.device("cpu"),
            target_update="polyak",
            hard_target_refresh_epochs=4,
        )
        raise AssertionError("Polyak mode accepted a hard refresh interval")
    except ValueError:
        pass


def test_c3_refreshes_twice_per_block_keeps_one_optimizer_and_exports_online(
    tmp_path, monkeypatch
):
    paths = _tiny_inputs(tmp_path)
    source_states = []

    def fake_targets(transitions_path, target_net, tmp_dir, **kwargs):
        source_states.append(
            [parameter.detach().cpu().clone() for parameter in target_net.parameters()]
        )
        return torch.zeros(16)

    monkeypatch.setattr(T, "compute_targets_streaming", fake_targets)

    hard_updates = []
    original_hard_update = T.hard_update_target_net

    def capture_hard_update(target_net, online_net):
        original_hard_update(target_net, online_net)
        hard_updates.append(
            (
                [p.detach().cpu().clone() for p in target_net.parameters()],
                [p.detach().cpu().clone() for p in online_net.parameters()],
            )
        )

    monkeypatch.setattr(T, "hard_update_target_net", capture_hard_update)

    original_adamw = torch.optim.AdamW
    optimizers = []

    def capture_adamw(*args, **kwargs):
        optimizer = original_adamw(*args, **kwargs)
        optimizers.append(optimizer)
        return optimizer

    monkeypatch.setattr(torch.optim, "AdamW", capture_adamw)

    original_net_class = T.EfficiencyQNet
    models = []

    def capture_net(*args, **kwargs):
        net = original_net_class(*args, **kwargs)
        models.append(net)
        return net

    monkeypatch.setattr(T, "EfficiencyQNet", capture_net)

    original_export = T.export_net_weights_dict
    exported_from = []
    exported_weights = []

    def capture_export(net):
        exported_from.append(net)
        weights = original_export(net)
        exported_weights.append(weights)
        return weights

    monkeypatch.setattr(T, "export_net_weights_dict", capture_export)

    ckpt_dir = tmp_path / "checkpoints"
    net, report = _run_tiny(
        paths,
        refresh_epochs=4,
        checkpoint_dir=ckpt_dir,
    )

    # One initial target copy plus two hard refreshes in each of two blocks.
    assert len(hard_updates) == 5
    for target_state, online_state in hard_updates:
        assert all(torch.equal(t, o) for t, o in zip(target_state, online_state))

    # Two target builds (train + val) for each of four half-blocks. Target
    # source is unchanged within a segment and refreshed between its halves.
    assert len(source_states) == 8
    assert all(
        torch.equal(a, b)
        for a, b in zip(source_states[0], source_states[1])
    )
    assert all(
        torch.equal(a, b)
        for a, b in zip(source_states[2], source_states[3])
    )
    assert any(
        not torch.equal(a, b)
        for a, b in zip(source_states[0], source_states[2])
    )
    assert all(
        torch.equal(a, b)
        for a, b in zip(source_states[2], hard_updates[1][0])
    ), "second segment uses the target copied after epoch 4"
    assert all(
        torch.equal(a, b)
        for a, b in zip(source_states[4], hard_updates[2][0])
    ), "next block begins from the target copied after prior epoch 8"
    assert all(
        torch.equal(a, b)
        for a, b in zip(source_states[6], hard_updates[3][0])
    ), "second block refreshes its target after epoch 4"

    # Optimizer state is not recreated at the midpoint or block boundary.
    assert len(optimizers) == 1
    steps = {int(state["step"].item()) for state in optimizers[0].state.values()}
    assert steps == {32}  # 2 blocks * 8 epochs * 2 batches/epoch.

    # Checkpoint serialization is invoked on the online model object, not the
    # target label source (even though hard-copy makes their boundary weights equal).
    assert len(models) == 2
    assert len(exported_from) == 2
    assert all(exported is models[0] for exported in exported_from)
    assert net is models[0]
    assert len(report["history"]) == 2
    assert report["config"]["hard_target_refresh_epochs"] == 4
    for block in (1, 2):
        with open(ckpt_dir / f"weights_iter{block:03d}.json", encoding="utf-8") as f:
            assert json.load(f) == exported_weights[block - 1]


def test_c3_uses_the_same_torch_permutation_stream_as_c1(tmp_path, monkeypatch):
    paths = _tiny_inputs(tmp_path)
    monkeypatch.setattr(T, "compute_targets_streaming", lambda *a, **k: torch.zeros(16))
    original_randperm = torch.randperm
    observed = []

    def capture_randperm(*args, **kwargs):
        permutation = original_randperm(*args, **kwargs)
        observed.append(permutation.detach().cpu().clone())
        return permutation

    monkeypatch.setattr(torch, "randperm", capture_randperm)
    _run_tiny(paths, refresh_epochs=None)
    c1_stream = [p.clone() for p in observed]
    observed.clear()
    _run_tiny(paths, refresh_epochs=4)
    c3_stream = [p.clone() for p in observed]

    assert len(c1_stream) == len(c3_stream) == 16
    assert all(torch.equal(a, b) for a, b in zip(c1_stream, c3_stream))
