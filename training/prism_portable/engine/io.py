"""Small bounded-memory identity and strict JSON helpers."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import torch


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def parse_json(text):
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_bad_constant)


def read_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8"))


def canonical_hash(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path, writer):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    text = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    _atomic_write(path, lambda stream: stream.write(text.encode("utf-8")))


def save_checkpoint(path, value):
    _atomic_write(path, lambda stream: torch.save(value, stream))


def tensor_manifest(state_dict):
    result = {}
    for key, tensor in sorted(state_dict.items()):
        if tensor.dtype != torch.float32 or not torch.isfinite(tensor).all():
            raise ValueError(f"{key}: weights must be finite float32")
        data = tensor.detach().cpu().contiguous().numpy().astype("<f4", copy=False)
        result[key] = {"shape": list(data.shape), "sha256": hashlib.sha256(data.tobytes()).hexdigest()}
    return result


def tensor_identity(state_dict):
    return canonical_hash(tensor_manifest(state_dict))
