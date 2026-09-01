"""Resident M40A inference server: load once, serve many games.

Identical wire protocol to the M39A resident server (a proven,
review-approved transport), but the model is an M40AModel whose value
readout is `V = p_win − p_loss` from the outcome head, and the response
additionally carries the raw outcome probabilities so the agent can
record them.
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
from .m39a_contract import file_sha256
from .m40a_constants import DESIGN_SHA, HEAD_INIT_SEED
from .m40a_model import (
    M40AModel,
    initialize_predictive_heads,
    load_d2_actor,
    outcome_value,
)

SERVER_FORMAT = "effective-splendor-m40a-inference-server"
SERVER_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024 * 1024

M40A_PLAN_CHECKPOINT_FILE_SHA256 = (
    "113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17"
)


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
    model: M40AModel,
    catalog: dict[str, Any],
    device: torch.device,
    identity: dict[str, Any],
) -> None:
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
                logits, heads = model.forward_packed(**encoded)
            outcome_probabilities = torch.softmax(
                heads["outcome"][0].to(dtype=torch.float32), dim=-1
            )
            value = float(outcome_value(heads["outcome"])[0].item())
            if not (
                torch.isfinite(logits).all()
                and outcome_probabilities.isfinite().all()
                and all(
                    torch.isfinite(heads[name]).all()
                    for name in (
                        "final_vp_self",
                        "final_vp_opp",
                        "vp_difference",
                        "timing",
                    )
                )
            ):
                raise ValueError("inference produced non-finite output")
            response = {
                "status": "ok",
                "logits": logits.detach().cpu().tolist(),
                "log_probabilities": None,  # filled by the frozen draw below
                "probabilities": None,
                "values": [value],  # single viewer-relative V (M40A readout)
                "auxiliary": float(heads["vp_difference"][0].item()),
                **identity,
            }
            # The frozen categorical draw needs torch f32 log-softmax
            # probabilities — computed here, server-side, so the agent's
            # stub performs the identical frozen draw as M39A.
            log_probs = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
            probabilities = log_probs.exp()
            response["log_probabilities"] = log_probs.detach().cpu().tolist()
            response["probabilities"] = probabilities.detach().cpu().tolist()
        except Exception as error:  # noqa: BLE001 - reported to the client
            response = {"status": "error", "message": str(error)}
        _send_message(connection, response)


def serve(
    *,
    checkpoint: Path | None,
    d2_checkpoint: Path,
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

    if checkpoint is not None:
        # The CLI-provided SHA is NEVER trusted: the actual file hash is
        # recomputed from disk and must match before anything proceeds.
        actual_file_sha = file_sha256(checkpoint)
        if actual_file_sha != checkpoint_sha256:
            raise ValueError(
                f"M40A checkpoint file SHA mismatch: expected {checkpoint_sha256}, "
                f"got {actual_file_sha}"
            )
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        # The semantic hash is a TOP-LEVEL payload field per the M40A
        # checkpoint convention — not metadata.
        semantic_hash = payload.get("checkpoint_hash")
        if not isinstance(semantic_hash, str):
            raise ValueError("M40A checkpoint lacks a top-level checkpoint_hash")
        model = M40AModel()
        model.load_state_dict(payload["state_dict"], strict=True)
        if payload["metadata"].get("plan_hash") != plan_hash:
            raise ValueError("M40A checkpoint plan hash mismatch")
        if payload["metadata"].get("arm") not in ("A", "B"):
            raise ValueError("M40A checkpoint metadata lacks a valid arm")
    else:
        actual_file_sha = file_sha256(d2_checkpoint)
        if actual_file_sha != M40A_PLAN_CHECKPOINT_FILE_SHA256:
            raise ValueError(
                f"D2-v2 checkpoint file SHA mismatch: expected "
                f"{M40A_PLAN_CHECKPOINT_FILE_SHA256}, got {actual_file_sha}"
            )
        model = M40AModel()
        load_d2_actor(model, d2_checkpoint, M40A_PLAN_CHECKPOINT_FILE_SHA256)
        initialize_predictive_heads(model, HEAD_INIT_SEED)
        semantic_hash = None
        payload = {"metadata": {"cycle": 0, "arm": None}}
    model.to(device)

    catalog_data = load_catalog(catalog)
    cat_hash = catalog_semantic_hash(catalog_data)
    if payload["metadata"].get("catalog_hash") not in (None, cat_hash):
        raise ValueError("checkpoint catalog hash does not match supplied catalog")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(64)
    bound_host, bound_port = server.getsockname()
    identity = {
        "server_format": SERVER_FORMAT,
        "checkpoint_sha256": checkpoint_sha256,  # verified above, not echoed
        "checkpoint_hash": semantic_hash,  # top-level payload field
        "checkpoint_cycle": int(payload["metadata"].get("cycle", 0)),
        "checkpoint_arm": payload["metadata"].get("arm"),
        "catalog_hash": cat_hash,
        "design_sha": DESIGN_SHA,
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
    parser = argparse.ArgumentParser(description="Resident M40A inference server")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--d2-checkpoint", type=Path, default=None)
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
    if args.checkpoint is None and args.d2_checkpoint is None:
        raise ValueError("either --checkpoint (M40A) or --d2-checkpoint (fresh) is required")
    if args.ready_file.exists():
        raise FileExistsError(f"ready file already exists: {args.ready_file}")
    serve(
        checkpoint=args.checkpoint.resolve() if args.checkpoint else None,
        d2_checkpoint=(args.d2_checkpoint or args.checkpoint).resolve(),
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
