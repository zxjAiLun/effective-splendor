"""Pinned Rust rules/projection auditor invocation, never a sidecar trust flag."""
from pathlib import Path
import subprocess

from ..io import parse_json, sha256_file
from .contract import sha

MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


def bounded_json(path, limit=MAX_ARTIFACT_BYTES):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("audit JSON input exceeds supported size")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("audit JSON input grew beyond supported size")
    return parse_json(data.decode("utf-8"))


def audit_game(executable, expected_sha256, replay, sidecar, output, *, behavior_id, job_id, actor):
    executable, replay, sidecar, output = map(Path, (executable, replay, sidecar, output))
    sha(expected_sha256, "auditor sha256")
    if sha256_file(executable) != expected_sha256:
        raise ValueError("auditor binary identity mismatch")
    if output.exists():
        raise ValueError("audit output already exists")
    for source in (replay, sidecar):
        if not source.is_file() or source.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("audit source exceeds supported size")
    inputs = (sha256_file(replay), sha256_file(sidecar))
    command = [str(executable.resolve()), "prism-ppo-audit", "--replay", str(replay.resolve()),
               "--sidecar", str(sidecar.resolve()), "--output", str(output.resolve()),
               "--behavior-id", behavior_id, "--job-id", job_id, "--actor", str(actor)]
    # No shell, network or matches: the binary strictly audits existing files.
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Rust PPO audit timed out") from exc
    if result.returncode != 0:
        raise ValueError(f"Rust PPO audit failed (exit {result.returncode})")
    if inputs != (sha256_file(replay), sha256_file(sidecar)) or sha256_file(executable) != expected_sha256:
        raise ValueError("audit inputs/binary changed during verification")
    game = bounded_json(output, MAX_ARTIFACT_BYTES + 16_384)
    if (game.get("replay_sha256"), game.get("sidecar_sha256")) != inputs:
        raise ValueError("audit source hashes mismatch")
    return game
