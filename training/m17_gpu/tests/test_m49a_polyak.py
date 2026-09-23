"""C2 Polyak target-update contract tests.

Frozen C2 rule: after each complete FQI iteration (all 8 epochs),
    target = 0.95 * target + 0.05 * online
- applied ONCE per FQI iteration (granularity: per iteration, not per batch/epoch);
- online net is never mutated by the target update;
- checkpoints/selection/evaluation use the ONLINE net; target net only
  generates Bellman labels.
"""

import json

import numpy as np
import torch

from splendor_gpu import m49a_trainer as T


def _filled_net(v: float) -> T.EfficiencyQNet:
    net = T.EfficiencyQNet(in_features=428)
    with torch.no_grad():
        for p in net.parameters():
            p.fill_(v)
    return net


def test_polyak_formula_and_online_untouched():
    target = _filled_net(100.0)
    online = _filled_net(20.0)
    online_before = [p.detach().clone() for p in online.parameters()]
    target_before = [p.detach().clone() for p in target.parameters()]

    T.polyak_update_target_net(target, online, 0.05)

    for tp, tb in zip(target.parameters(), target_before):
        assert torch.allclose(tp, 0.95 * tb + 0.05 * 20.0, atol=1e-6)
    for op, ob in zip(online.parameters(), online_before):
        assert torch.equal(op, ob), "online net must not be mutated"


def test_polyak_tau_bounds():
    target, online = _filled_net(1.0), _filled_net(2.0)
    for bad in (0.0, -0.05, 1.01, float("nan")):
        try:
            T.polyak_update_target_net(target, online, bad)
            raise AssertionError(f"tau={bad} accepted")
        except ValueError:
            pass


def test_invalid_target_update_rejected_before_io(tmp_path):
    # Validation happens before any dataset I/O, so dummy paths are sufficient.
    for invalid_mode in ("soft", "ema", "HARD", ""):
        try:
            T.train_fqi_streaming(
                tmp_path / "no.f32", tmp_path / "no.jsonl",
                tmp_path / "no2.f32", tmp_path / "no2.jsonl",
                device=torch.device("cpu"), target_update=invalid_mode,
            )
            raise AssertionError(f"target_update={invalid_mode!r} accepted")
        except ValueError:
            pass
    try:
        T.train_fqi_streaming(
            tmp_path / "no.f32", tmp_path / "no.jsonl",
            tmp_path / "no2.f32", tmp_path / "no2.jsonl",
            device=torch.device("cpu"), target_update="polyak", polyak_tau=0.0,
        )
        raise AssertionError("polyak_tau=0 accepted")
    except ValueError:
        pass


def _tiny_x(tmp_path, n=16):
    paths = {}
    for split in ("train", "val"):
        np.zeros((n, 428), dtype=np.float32).tofile(tmp_path / f"{split}_x.f32")
        (tmp_path / f"{split}_transitions.jsonl").write_text("")
        paths[split] = tmp_path / f"{split}_x.f32"
    return paths


class TestRealLoopWiring:
    def test_target_update_once_per_fqi_and_checkpoints_are_online(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(T, "compute_targets_streaming",
                            lambda *a, **k: torch.zeros(16))
        captured = {}  # iteration -> (target_state, online_state) after update
        orig = T.polyak_update_target_net

        def spy(target, online, tau):
            assert tau == 0.05
            orig(target, online, tau)
            captured[len(captured) + 1] = (
                T.export_net_weights_dict(target),
                T.export_net_weights_dict(online),
            )

        monkeypatch.setattr(T, "polyak_update_target_net", spy)

        ck_dir = tmp_path / "ckpts"
        paths = _tiny_x(tmp_path)
        net, report = T.train_fqi_streaming(
            paths["train"], tmp_path / "train_transitions.jsonl",
            paths["val"], tmp_path / "val_transitions.jsonl",
            device=torch.device("cpu"), epochs_per_fqi=1, fqi_iterations=2,
            batch_size=8, seed=49000001, checkpoint_dir=ck_dir,
            checkpoint_every=1, target_update="polyak", polyak_tau=0.05,
        )

        assert sorted(captured) == [1, 2], "exactly one update per FQI iteration"
        for it in (1, 2):
            with open(ck_dir / f"weights_iter{it:03d}.json") as f:
                ck = json.load(f)
            tgt, online = captured[it]
            assert ck == online, f"iter{it} checkpoint must be the ONLINE net"
            assert ck != tgt, f"iter{it} checkpoint must NOT be the target net"
            assert tgt != online, "polyak target must differ from online"

        # Recursive check: target_k = 0.95 * target_{k-1} + 0.05 * online_k
        # for k >= 2 (target_0 was a hard copy of online_0 and is not captured).
        for it in (2,):
            tgt, online = captured[it]
            prev = captured[it - 1][0]
            for key, val in tgt.items():
                arr = np.array(val, dtype=np.float64)
                onl = np.array(online[key], dtype=np.float64)
                expected = 0.95 * np.array(prev[key], dtype=np.float64) + 0.05 * onl
                assert np.allclose(arr, expected, atol=1e-6), (it, key)

    def test_hard_mode_never_calls_polyak(self, tmp_path, monkeypatch):
        monkeypatch.setattr(T, "compute_targets_streaming",
                            lambda *a, **k: torch.zeros(16))
        calls = []

        def forbidden(*a, **k):
            calls.append(1)
            raise AssertionError("polyak_update called in hard mode")

        monkeypatch.setattr(T, "polyak_update_target_net", forbidden)
        paths = _tiny_x(tmp_path)
        net, report = T.train_fqi_streaming(
            paths["train"], tmp_path / "train_transitions.jsonl",
            paths["val"], tmp_path / "val_transitions.jsonl",
            device=torch.device("cpu"), epochs_per_fqi=1, fqi_iterations=2,
            batch_size=8, seed=49000001, target_update="hard",
        )
        assert not calls
        assert report["config"]["target_update"] == "hard"
        assert report["config"]["polyak_tau"] is None
