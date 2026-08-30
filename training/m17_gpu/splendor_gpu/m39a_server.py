"""Resident M39A inference server: load once, serve many games.

The per-game agent architecture paid a full `import torch` + checkpoint load
+ CUDA-context creation for every game and every seat, which starved the
frozen 10-second Arena handshake under concurrent load and left the GPU idle
most of the time. This module keeps exactly one model instance, one catalog,
and one CUDA context alive and serves inference requests over a local TCP
socket, so the per-game agent process becomes a lightweight proxy.

The server performs ONLY the deterministic forward pass. Categorical
sampling, seed derivation, sidecar writing, and every protocol check stay in
the per-game agent (`m39a_agent.py`), so the provenance contract is
unchanged: the agent still derives `decision_seed` locally and the stub
records exactly what it asked the server to compute.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import torch

from .data import catalog_semantic_hash, load_catalog
from .m39a_contract import file_sha256
from .m39a_model import load_m39a_checkpoint

SERVER_FORMAT = "effective-splendor-m39a-inference-server"
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
    catalog: dict[str, Any],
    device: torch.device,
    identity: dict[str, Any],
) -> None:
    """Serve newline-delimited inference requests on one connection."""
    from .m39a_model import encode_decisions, move_encoded

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
            encoded = move_encoded(
                encode_decisions([observation], [legal_actions], catalog), device
            )
            with torch.no_grad():
                logits, values, auxiliary = model.forward_packed(**encoded)
            if not (
                torch.isfinite(logits).all()
                and torch.isfinite(values).all()
                and torch.isfinite(auxiliary).all()
            ):
                raise ValueError("inference produced non-finite output")
            log_probs = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
            probabilities = log_probs.exp()
            response = {
                "status": "ok",
                "logits": logits.detach().cpu().tolist(),
                "log_probabilities": log_probs.detach().cpu().tolist(),
                "probabilities": probabilities.detach().cpu().tolist(),
                "values": values[0].detach().cpu().tolist(),
                "auxiliary": float(auxiliary[0].item()),
                **identity,
            }
        except Exception as error:  # noqa: BLE001 - reported to the client
            response = {"status": "error", "message": str(error)}
        _send_message(connection, response)


def serve(
    *,
    checkpoint: Path,
    checkpoint_sha256: str,
    plan_hash: str,
    catalog: Path,
    host: str,
    port: int,
    device: torch.device,
    ready_path: Path,
) -> None:
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(1)

    model, payload = load_m39a_checkpoint(
        checkpoint,
        expected_file_sha256=checkpoint_sha256,
        expected_plan_hash=plan_hash,
        device=device,
    )
    catalog_data = load_catalog(catalog)
    cat_hash = catalog_semantic_hash(catalog_data)
    if payload["metadata"].get("catalog_hash") != cat_hash:
        raise ValueError("checkpoint catalog hash does not match supplied catalog")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(64)
    bound_host, bound_port = server.getsockname()
    identity = {
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash": payload["checkpoint_hash"],
        "checkpoint_cycle": int(payload["metadata"]["cycle"]),
        "catalog_hash": cat_hash,
    }
    ready = {
        "format": SERVER_FORMAT,
        "version": SERVER_VERSION,
        "host": bound_host,
        "port": int(bound_port),
        **identity,
        "plan_hash": plan_hash,
        "device": str(device),
        "torch_version": torch.__version__,
        "pid": os.getpid(),
    }
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ready_path.with_name(ready_path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, ready_path)
    print(json.dumps({"status": "ready", **ready}, separators=(",", ":")), flush=True)

    try:
        while True:
            connection, _ = server.accept()
            thread = threading.Thread(
                target=handle_connection,
                args=(connection, model, catalog_data, device, identity),
                daemon=True,
            )
            thread.start()
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resident M39A inference server")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    if args.ready_file.exists():
        raise FileExistsError(f"ready file already exists: {args.ready_file}")
    serve(
        checkpoint=args.checkpoint.resolve(),
        checkpoint_sha256=args.checkpoint_sha256,
        plan_hash=args.plan_hash,
        catalog=args.catalog.resolve(),
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
