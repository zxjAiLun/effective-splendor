from __future__ import annotations

import json
import math
import socket
import threading
from pathlib import Path

import pytest

from splendor_gpu.m39a_agent import ServerProxy, _log_softmax, categorical_index


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeServer:
    """In-process stand-in for m39a_server speaking the same wire format."""

    def __init__(self, identity: dict) -> None:
        self.identity = identity
        self.requests: list[dict] = []
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            with connection:
                while True:
                    data = b""
                    while b"\n" not in data:
                        chunk = connection.recv(65536)
                        if not chunk:
                            return
                        data += chunk
                    request = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
                    self.requests.append(request)
                    response = {
                        "status": "ok",
                        "logits": [0.25, -1.5, 2.0],
                        "log_probabilities": _log_softmax([0.25, -1.5, 2.0], f32=True),
                        "probabilities": [
                            math.exp(lp)
                            for lp in _log_softmax([0.25, -1.5, 2.0], f32=True)
                        ],
                        "values": [0.1, -0.1],
                        "auxiliary": 0.05,
                        **self.identity,
                    }
                    connection.sendall(
                        json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
                    )

    def close(self) -> None:
        self._socket.close()


@pytest.fixture()
def fake_server(tmp_path: Path):
    identity = {
        "checkpoint_sha256": "abc123",
        "checkpoint_hash": "semantic-abc",
        "checkpoint_cycle": 0,
        "catalog_hash": "catalog-hash",
    }
    server = _FakeServer(identity)
    ready = tmp_path / "server-ready.json"
    ready.write_text(
        json.dumps(
            {
                "format": "effective-splendor-m39a-inference-server",
                "version": 1,
                "host": "127.0.0.1",
                "port": server.port,
                **identity,
                "plan_hash": "plan-hash",
            }
        ),
        encoding="utf-8",
    )
    yield server, ready
    server.close()


def test_server_proxy_roundtrip_and_identity_verification(fake_server) -> None:
    server, ready = fake_server
    proxy = ServerProxy(
        f"127.0.0.1:{server.port}",
        ready,
        expected_plan_hash="plan-hash",
        expected_checkpoint_sha256="abc123",
    )
    logits, values, auxiliary, log_probs, probabilities = proxy.infer(
        {"tokens": {}}, [{"type": "pass"}]
    )
    proxy.close()
    assert logits == [0.25, -1.5, 2.0]
    assert values == [0.1, -0.1]
    assert auxiliary == pytest.approx(0.05)
    assert log_probs == _log_softmax([0.25, -1.5, 2.0], f32=True)
    assert probabilities == [
        math.exp(lp) for lp in _log_softmax([0.25, -1.5, 2.0], f32=True)
    ]
    assert server.requests == [
        {"observation": {"tokens": {}}, "legal_actions": [{"type": "pass"}]}
    ]


def test_server_proxy_rejects_identity_mismatch(fake_server, tmp_path: Path) -> None:
    server, ready = fake_server
    forged = tmp_path / "forged-ready.json"
    payload = json.loads(ready.read_text(encoding="utf-8"))
    payload["checkpoint_sha256"] = "different-checkpoint"
    forged.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint_sha256 mismatch"):
        ServerProxy(
            f"127.0.0.1:{server.port}",
            forged,
            expected_plan_hash="plan-hash",
            expected_checkpoint_sha256="abc123",
        )


def test_server_proxy_rejects_in_flight_binding_change(fake_server) -> None:
    server, ready = fake_server
    server.identity["checkpoint_hash"] = "swapped-mid-flight"
    proxy = ServerProxy(
        f"127.0.0.1:{server.port}",
        ready,
        expected_plan_hash="plan-hash",
        expected_checkpoint_sha256="abc123",
    )
    with pytest.raises(RuntimeError, match="binding mismatch"):
        proxy.infer({"tokens": {}}, [{"type": "pass"}])
    proxy.close()


def test_categorical_index_matches_torch_f32() -> None:
    torch = pytest.importorskip("torch")
    torch.manual_seed(7)
    for _ in range(500):
        n = int(torch.randint(1, 60, (1,)).item())
        logits = torch.randn(n) * 3
        seed = int(torch.randint(0, 2**63 - 1, (1,)).item())
        reference = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
        probabilities = reference.exp().tolist()
        unit = (seed >> 11) * (2.0 ** -53)
        cumulative = 0.0
        expected_index = len(probabilities) - 1
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if unit < cumulative:
                expected_index = index
                break
        chosen, log_probability = categorical_index(logits.tolist(), seed)
        assert chosen == expected_index
        assert log_probability == pytest.approx(
            float(reference[expected_index].item()), abs=1e-6
        )


def test_categorical_index_list_and_tensor_agree() -> None:
    torch = pytest.importorskip("torch")
    torch.manual_seed(11)
    logits = torch.randn(31) * 2
    seed = 987654321
    from_tensor = categorical_index(logits, seed)
    from_list = categorical_index(logits.tolist(), seed)
    assert from_tensor == from_list


def test_frozen_draw_reviewer_boundary_vector() -> None:
    """The discriminating vector from the 2026-08-30 throughput-review HOLD.

    seed 2058960467996672 on logits [-9.10033082897735, 0.0]: the frozen
    torch-f32 pipeline (log_softmax -> exp -> tolist -> python cumulative)
    selects action 0 because the f32 probability 0.00011161647125845775 is
    above the draw unit 0.00011161647062318814, while re-exponentiating the
    log-probability in python f64 yields 0.00011161641270072074 — below the
    unit — and would wrongly select action 1. The stub must walk the
    server-provided torch f32 probabilities, never ``math.exp(logp)``.
    """
    torch = pytest.importorskip("torch")
    from splendor_gpu.m39a_agent import frozen_draw

    seed = 2058960467996672
    logits = [-9.10033082897735, 0.0]
    reference = torch.log_softmax(torch.tensor(logits, dtype=torch.float32), dim=0)
    log_probabilities = reference.tolist()
    probabilities = reference.exp().tolist()

    chosen, log_probability = frozen_draw(probabilities, log_probabilities, logits, seed)
    assert chosen == 0
    assert log_probability == float(reference[0].item())

    # The forbidden path (f64 re-exponentiation) provably diverges here:
    unit = (seed >> 11) * (2.0 ** -53)
    f64_probability = math.exp(log_probabilities[0])
    assert f64_probability < unit < probabilities[0]


def test_frozen_draw_matches_old_frozen_implementation() -> None:
    """frozen_draw over torch f32 probabilities is identical to the original
    per-process frozen draw across randomized vectors."""
    torch = pytest.importorskip("torch")
    from splendor_gpu.m39a_agent import frozen_draw

    torch.manual_seed(42)
    for _ in range(2000):
        n = int(torch.randint(1, 60, (1,)).item())
        logits = torch.randn(n) * 4
        seed = int(torch.randint(0, 2**63 - 1, (1,)).item())
        reference = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
        probabilities = reference.exp().cpu().tolist()
        unit = (seed >> 11) * (2.0 ** -53)
        cumulative = 0.0
        expected_index = len(probabilities) - 1
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if unit < cumulative:
                expected_index = index
                break
        chosen, log_probability = frozen_draw(
            probabilities, reference.tolist(), logits, seed
        )
        assert chosen == expected_index
        assert log_probability == float(reference[expected_index].item())
