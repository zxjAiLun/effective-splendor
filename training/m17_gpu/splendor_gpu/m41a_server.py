"""M41A resident inference server: ONE frozen M25-D2-v2 model loaded
once, serving branch-continuation inference over a local TCP socket.

Executor-optimization contract (authorized 2026-09-04): the server
performs ONLY the deterministic forward pass of the D2-v2 policy scorer
— identical math to `m35a_agent`'s in-process path. Argmax selection,
the agent protocol, belief/event handling, and every check remain in
the lightweight per-branch proxy (`m41a_proxy_agent.py`). The
equivalence gate (frozen pilot branches, old vs new executor) must show
bitwise-identical trajectories.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import torch

from .data import catalog_semantic_hash, load_catalog
from .m35a_registry import load_and_validate_checkpoint

SERVER_FORMAT = "effective-splendor-m41a-inference-server"
SERVER_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024 * 1024


def _recv_message(connection: socket.socket) -> dict[str, Any] | None:
    chunks = []
    total = 0
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            if total == 0:
                return None
            raise ConnectionError("connection closed mid-message")
        total += len(chunk)
        if total > MAX_REQUEST_BYTES:
            raise ConnectionError("request exceeds size bound")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    data = b"".join(chunks)
    line, _, remainder = data.partition(b"\n")
    if remainder.strip():
        raise ConnectionError("unexpected trailing bytes after request")
    return json.loads(line.decode("utf-8"))


def _send_message(connection: socket.socket, payload: dict[str, Any]) -> None:
    connection.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


def handle_connection(
    connection: socket.socket,
    model: torch.nn.Module,
    entry: Any,
    catalog: dict[str, Any],
    device: torch.device,
    identity: dict[str, Any],
) -> None:
    from .m35a_adapters import score_model_actions

    class _NullTracker:
        """D2-v2 (59-dim delta) never reads belief features; the
        tracker placeholder exists only because score_model_actions
        takes one. It is never consulted for global_feature_dim 40."""

        def project_features(self, observation, catalog):
            raise AssertionError("D2-v2 must never project belief features")

    model.eval()
    while True:
        try:
            request = _recv_message(connection)
        except (ConnectionError, json.JSONDecodeError):
            return
        if request is None:
            return
        try:
            observation = request["observation"]
            legal_actions = request["legal_actions"]
            if not isinstance(legal_actions, list) or not legal_actions:
                raise ValueError("legal_actions must be a non-empty list")
            with torch.no_grad():
                scores = score_model_actions(
                    model, entry, observation, legal_actions,
                    _NullTracker(), catalog, device,
                )
            if not torch.isfinite(scores).all():
                raise ValueError("inference produced non-finite output")
            response = {
                "status": "ok",
                "scores": scores.detach().cpu().tolist(),
                **identity,
            }
        except Exception as error:  # noqa: BLE001 - reported to the client
            response = {"status": "error", "message": str(error)}
        _send_message(connection, response)


def _semantic_hash(model: torch.nn.Module) -> str:
    """Canonical state_dict hash (the M40A checkpoint_semantic_hash
    recipe): SHA-256 over the ordered (name, shape, dtype, bytes)."""
    import hashlib

    hasher = hashlib.sha256()
    state = model.state_dict()
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        hasher.update(name.encode("utf-8"))
        hasher.update(str(tuple(tensor.shape)).encode("utf-8"))
        hasher.update(str(tensor.dtype).encode("utf-8"))
        hasher.update(tensor.numpy().tobytes())
    return hasher.hexdigest()


def serve(
    *,
    model_id: str,
    checkpoint_sha256: str,
    catalog_path: Path,
    host: str,
    port: int,
    device: torch.device,
    ready_path: Path,
) -> None:
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(1)

    catalog = load_catalog(catalog_path)
    cat_hash = catalog_semantic_hash(catalog)
    model, entry = load_and_validate_checkpoint(
        model_id=model_id, catalog_hash=cat_hash, device=device
    )
    # The CLI-supplied SHA is NEVER trusted: recomputed from disk.
    from .m39a_contract import file_sha256

    actual_sha = file_sha256(Path(entry.checkpoint_path))
    if actual_sha != checkpoint_sha256:
        raise ValueError(
            f"checkpoint SHA mismatch: expected {checkpoint_sha256}, got {actual_sha}"
        )
    semantic = _semantic_hash(model)

    identity = {
        "model_id": model_id,
        "checkpoint_sha256": actual_sha,
        "checkpoint_semantic_sha256": semantic,
        "catalog_hash": cat_hash,
        "server_source_sha256": file_sha256(Path(__file__).resolve()),
    }

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(64)
    bound_host, bound_port = server.getsockname()
    ready = {
        "format": SERVER_FORMAT,
        "version": SERVER_VERSION,
        "host": bound_host,
        "port": int(bound_port),
        **identity,
    }
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ready_path.with_name(ready_path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, ready_path)
    print(json.dumps({"status": "ready", **ready}), flush=True)

    try:
        while True:
            connection, _ = server.accept()
            thread = threading.Thread(
                target=handle_connection,
                args=(connection, model, entry, catalog, device, identity),
                daemon=True,
            )
            thread.start()
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A resident D2-v2 inference server")
    parser.add_argument("--model-id", default="M25-D2-v2")
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    serve(
        model_id=args.model_id,
        checkpoint_sha256=args.checkpoint_sha256,
        catalog_path=args.catalog.resolve(),
        host=args.host,
        port=args.port,
        device=torch.device(args.device),
        ready_path=args.ready_file.resolve(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
