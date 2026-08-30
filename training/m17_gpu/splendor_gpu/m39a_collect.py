"""Resumable Arena collector for one M39A PPO cycle.

This driver never uses a shell.  It realizes the frozen Python schedule into
per-game Arena configs, launches the existing Rust referee, preserves full
terminal report/replay artifacts, and finally invokes the Rust authoritative
materializer.  Existing complete game directories are resumed; partial game
artifacts fail closed instead of being overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .data import catalog_semantic_hash, load_catalog
from .m35a_registry import REGISTRY, compute_file_sha256
from .m39a_contract import file_sha256, load_plan, plan_hash, scheduled_game
from .m39a_model import load_m39a_checkpoint


MANIFEST_FORMAT = "effective-splendor-m39a-materialization-manifest"
MANIFEST_VERSION = 1
M39A_AGENT_NAME = "effective-splendor-m39a-policy-value-agent-v1"

# Arena-spawned agent processes inherit this process's environment, and both
# the resident and proxy agent entry points import the splendor_gpu package.
# Propagate the module root this driver was imported from so collection works
# regardless of how the driver itself was launched.
_MODULE_ROOT = str(Path(__file__).resolve().parent.parent)
if _MODULE_ROOT not in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    os.environ["PYTHONPATH"] = (
        _MODULE_ROOT + os.pathsep + os.environ["PYTHONPATH"]
        if os.environ.get("PYTHONPATH")
        else _MODULE_ROOT
    )


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _m39a_agent(
    *,
    checkpoint: Path,
    checkpoint_sha256: str,
    digest: str,
    game_index: int,
    sidecar: Path,
    catalog: Path,
    device: str,
    action_selection: str = "categorical",
    server_url: str | None = None,
    server_ready: Path | None = None,
) -> dict[str, Any]:
    args = [
        "-m",
        "splendor_gpu.m39a_agent",
        "--checkpoint-sha256",
        checkpoint_sha256,
        "--plan-hash",
        digest,
        "--game-index",
        str(game_index),
        "--sidecar-out",
        str(sidecar),
    ]
    if server_url is not None:
        if server_ready is None:
            raise ValueError("server_url requires server_ready")
        args.extend(["--server-url", server_url, "--server-ready", str(server_ready)])
    else:
        args.extend(
            [
                "--checkpoint",
                str(checkpoint),
                "--catalog",
                str(catalog),
                "--device",
                device,
            ]
        )
    args.extend(["--action-selection", action_selection])
    return {
        "program": str(Path(sys.executable).resolve()),
        "args": args,
    }


def _opponent_agent(
    opponent: str,
    *,
    splendor: Path,
    catalog: Path,
    action_seed: int,
    device: str,
) -> dict[str, Any]:
    if opponent == "agent-random":
        return {
            "program": str(splendor),
            "args": ["agent-random", "--seed", str(action_seed)],
        }
    if opponent == "agent-heuristic":
        return {
            "program": str(splendor),
            "args": ["agent-heuristic", "--seed", str(action_seed)],
        }
    if opponent == "M07":
        return {
            "program": str(splendor),
            "args": [
                "agent-determinization",
                "--sample-seed",
                "20260810",
                "--sample-count",
                "4",
                "--max-depth-turns",
                "1",
                "--max-nodes",
                "2000",
            ],
        }
    if opponent not in REGISTRY:
        raise ValueError(f"unsupported scheduled opponent {opponent!r}")
    return {
        "program": str(Path(sys.executable).resolve()),
        "args": [
            "-m",
            "splendor_gpu.m35a_agent",
            "--model-id",
            opponent,
            "--catalog",
            str(catalog),
            "--device",
            device,
        ],
    }


def preflight_league() -> None:
    for model_id, entry in REGISTRY.items():
        if not entry.checkpoint_path.is_file():
            raise FileNotFoundError(
                f"league checkpoint missing for {model_id}: {entry.checkpoint_path}"
            )
        actual = compute_file_sha256(entry.checkpoint_path)
        if actual != entry.checkpoint_file_sha256:
            raise ValueError(
                f"league checkpoint SHA mismatch for {model_id}: "
                f"expected {entry.checkpoint_file_sha256}, got {actual}"
            )


def _relative_to_manifest(path: Path, manifest_path: Path) -> str:
    return os.path.relpath(path, manifest_path.parent).replace("\\", "/")


class ResidentServer:
    """Lifecycle wrapper around one resident m39a_server process.

    Spawns the server once, waits for its ready file (which carries the
    verified checkpoint/plan/catalog identity), and exposes the URL plus
    ready-file path that per-game proxy agents need. On exit the server
    process is terminated.
    """

    def __init__(
        self,
        *,
        checkpoint: Path,
        checkpoint_sha256: str,
        plan_hash: str,
        catalog: Path,
        device: str,
        ready_file: Path,
        startup_timeout_seconds: float = 120.0,
    ) -> None:
        self._ready_file = ready_file
        if ready_file.exists():
            # A ready file from a previous collection run refers to a server
            # that is no longer alive. Validate its identity, then replace it
            # by starting a fresh server for this run.
            previous = json.loads(ready_file.read_text(encoding="utf-8"))
            for field, expected in (
                ("checkpoint_sha256", checkpoint_sha256),
                ("plan_hash", plan_hash),
            ):
                if previous.get(field) != expected:
                    raise ValueError(
                        f"previous server ready file {field} mismatch: "
                        f"expected {expected!r}, got {previous.get(field)!r}"
                    )
            ready_file.unlink()
        environment = dict(os.environ)
        module_root = str(Path(__file__).resolve().parent.parent)
        existing = environment.get("PYTHONPATH")
        if existing:
            environment["PYTHONPATH"] = os.pathsep.join([module_root, existing])
        else:
            environment["PYTHONPATH"] = module_root
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "splendor_gpu.m39a_server",
                "--checkpoint",
                str(checkpoint),
                "--checkpoint-sha256",
                checkpoint_sha256,
                "--plan-hash",
                plan_hash,
                "--catalog",
                str(catalog),
                "--device",
                device,
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        deadline = time.time() + startup_timeout_seconds
        while not ready_file.is_file():
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise RuntimeError(f"resident server exited during startup: {stderr}")
            if time.time() > deadline:
                self._process.terminate()
                raise TimeoutError(
                    f"resident server did not become ready within {startup_timeout_seconds}s"
                )
            time.sleep(0.1)
        ready = json.loads(ready_file.read_text(encoding="utf-8"))
        self.url = f"{ready['host']}:{ready['port']}"
        self.ready_file = ready_file
        self.identity = {
            "checkpoint_sha256": ready["checkpoint_sha256"],
            "checkpoint_hash": ready["checkpoint_hash"],
            "checkpoint_cycle": int(ready["checkpoint_cycle"]),
            "catalog_hash": ready["catalog_hash"],
        }

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)


def _collect_games(
    *,
    server: "ResidentServer | None",
    plan: dict[str, Any],
    digest: str,
    checkpoint: Path,
    checkpoint_sha256: str,
    cycle: int,
    count: int,
    start: int,
    catalog_path: Path,
    splendor: Path,
    out_dir: Path,
    device: str,
    sources: list[dict[str, Any]],
    elapsed: list[float],
) -> None:
    ply_cap = int(plan["round"]["ply_cap"])
    for game_index in range(start, start + count):
        game = scheduled_game(game_index)
        game_dir = out_dir / "games" / f"game-{game_index:06d}"
        config_path = game_dir / "arena-config.json"
        report_path = game_dir / "arena-report.json"
        replay_path = game_dir / "replay.json"
        prefix_path = game_dir / "rollout-prefix.json"
        sidecars = {
            seat: game_dir / f"seat-{seat}.sidecar.json" for seat in game.learner_seats
        }
        # A completed game has its authoritative document (replay for
        # terminal games, prefix for truncated ones) plus report and sidecars.
        # Any partial combination of report/replay/prefix/sidecars is
        # preserved evidence of an interrupted run and fails closed.
        report_exists = report_path.exists()
        replay_exists = replay_path.exists()
        prefix_exists = prefix_path.exists()
        sidecars_exist = [path.exists() for path in sidecars.values()]
        if report_exists and (replay_exists or prefix_exists) and all(sidecars_exist):
            # Complete (resumed) game: validate the artifact shape.
            if replay_exists and prefix_exists:
                raise RuntimeError(
                    f"game {game_index} has both replay and prefix: {game_dir}"
                )
        elif not (report_exists or replay_exists or prefix_exists or any(sidecars_exist)):
            # Nothing exists yet (a stale config-only directory is also fine:
            # the game never started, so there is no data to preserve; the
            # stale config embedding the previous server URL is rewritten).
            pass
        else:
            raise RuntimeError(
                f"game {game_index} has partial artifacts; preserve and diagnose them: {game_dir}"
            )
        if not report_exists:
            if config_path.exists() and not (replay_exists or prefix_exists):
                # config-only from an interrupted run: safe to rewrite.
                config_path.unlink()
            game_dir.mkdir(parents=True, exist_ok=True)
            agents = []
            for seat in (0, 1):
                if seat in game.learner_seats:
                    agents.append(
                        _m39a_agent(
                            checkpoint=checkpoint,
                            checkpoint_sha256=checkpoint_sha256,
                            digest=digest,
                            game_index=game_index,
                            sidecar=sidecars[seat],
                            catalog=catalog_path,
                            device=device,
                            server_url=server.url if server is not None else None,
                            server_ready=server.ready_file if server is not None else None,
                        )
                    )
                else:
                    agents.append(
                        _opponent_agent(
                            game.opponent,
                            splendor=splendor,
                            catalog=catalog_path,
                            action_seed=20_260_830 + game_index,
                            device=device,
                        )
                    )
            config = {
                "game_id": f"m39a-cycle-{cycle}-game-{game_index:06d}",
                "seed": game.seed,
                "handshake_timeout_ms": 10_000,
                "move_timeout_ms": 30_000,
                "shutdown_grace_ms": 2_000,
                "agents": agents,
            }
            _write_new_json(config_path, config)
            started = time.perf_counter()
            completed = subprocess.run(
                [
                    str(splendor),
                    "run-rollout",
                    "--max-plies",
                    str(ply_cap),
                    "--config",
                    str(config_path),
                    "--report-out",
                    str(report_path),
                    "--replay-out",
                    str(replay_path),
                    "--prefix-out",
                    str(prefix_path),
                ],
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                timeout=60 * 60,
                check=False,
            )
            duration = time.perf_counter() - started
            elapsed.append(duration)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Arena game {game_index} failed rc={completed.returncode}: "
                    f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
                )
            replay_exists = replay_path.is_file()
            prefix_exists = prefix_path.is_file()
            if (
                not report_path.is_file()
                or (replay_exists == prefix_exists)  # exactly one must exist
                or any(not path.is_file() for path in sidecars.values())
            ):
                raise RuntimeError(f"Arena game {game_index} did not publish every artifact")
            outcome_status = None
            if report_path.is_file():
                outcome = json.loads(report_path.read_text(encoding="utf-8")).get("outcome", {})
                outcome_status = outcome.get("status")
            if outcome_status not in ("completed", "truncated"):
                raise RuntimeError(
                    f"Arena game {game_index} produced unexpected outcome {outcome_status!r}"
                )
            print(
                json.dumps(
                    {
                        "game_index": game_index,
                        "bucket": game.bucket,
                        "opponent": game.opponent,
                        "seconds": duration,
                        "status": outcome_status,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        else:
            outcome = json.loads(report_path.read_text(encoding="utf-8")).get("outcome", {})
            print(
                json.dumps(
                    {
                        "game_index": game_index,
                        "status": "resumed",
                        "outcome": outcome.get("status"),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        sources.append(
            {
                "game_index": game_index,
                "report_path": "",
                "replay_path": "",
                "prefix_path": "",
                "sidecar_paths": [],
            }
        )


def collect(
    *,
    plan_path: Path,
    checkpoint: Path,
    checkpoint_sha256: str,
    checkpoint_hash: str,
    cycle: int,
    catalog_path: Path,
    splendor: Path,
    out_dir: Path,
    mode: str,
    smoke_games: int,
    device: str,
    materialize: bool,
    batch_out: Path | None,
    resident_server: bool = True,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    digest = plan_hash(plan)
    if plan["catalog"]["semantic_hash"] != catalog_semantic_hash(load_catalog(catalog_path)):
        raise ValueError("catalog does not match plan")
    model, payload = load_m39a_checkpoint(
        checkpoint,
        expected_file_sha256=checkpoint_sha256,
        expected_plan_hash=digest,
        device="cpu",
    )
    del model
    metadata = payload["metadata"]
    if int(metadata["cycle"]) != cycle - 1 or payload["checkpoint_hash"] != checkpoint_hash:
        raise ValueError("checkpoint cycle/semantic hash does not match collection request")
    if mode == "complete_cycle" and device != "cuda":
        raise ValueError("complete_cycle collection requires the frozen cuda runtime")
    if mode == "complete_cycle":
        preflight_league()
        count = 512
    else:
        if not 1 <= smoke_games <= 512:
            raise ValueError("smoke_games must be in 1..=512")
        count = smoke_games

    plan_path = plan_path.resolve()
    checkpoint = checkpoint.resolve()
    catalog_path = catalog_path.resolve()
    splendor = splendor.resolve()
    out_dir = out_dir.resolve()
    if not splendor.is_file():
        raise FileNotFoundError(f"splendor binary not found: {splendor}")
    start = (cycle - 1) * 512
    sources: list[dict[str, Any]] = []
    elapsed: list[float] = []
    server: ResidentServer | None = None
    if resident_server:
        ready_file = out_dir / "server-ready.json"
        server = ResidentServer(
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256,
            plan_hash=digest,
            catalog=catalog_path,
            device=device,
            ready_file=ready_file,
        )
    try:
        _collect_games(
            server=server,
            plan=plan,
            digest=digest,
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha256,
            cycle=cycle,
            count=count,
            start=start,
            catalog_path=catalog_path,
            splendor=splendor,
            out_dir=out_dir,
            device=device,
            sources=sources,
            elapsed=elapsed,
        )
    finally:
        if server is not None:
            server.close()

    manifest_path = out_dir / "materialization-manifest.json"
    for source, game_index in zip(sources, range(start, start + count)):
        game_dir = out_dir / "games" / f"game-{game_index:06d}"
        game = scheduled_game(game_index)
        source["report_path"] = _relative_to_manifest(
            game_dir / "arena-report.json", manifest_path
        )
        replay_path = game_dir / "replay.json"
        prefix_path = game_dir / "rollout-prefix.json"
        if replay_path.is_file() and prefix_path.is_file():
            raise RuntimeError(f"game {game_index} has both replay and prefix")
        source["replay_path"] = _relative_to_manifest(replay_path, manifest_path)
        if prefix_path.is_file():
            source["prefix_path"] = _relative_to_manifest(prefix_path, manifest_path)
        source["sidecar_paths"] = [
            _relative_to_manifest(game_dir / f"seat-{seat}.sidecar.json", manifest_path)
            for seat in game.learner_seats
        ]
    manifest = {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "mode": mode,
        "plan_hash": digest,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_cycle": cycle - 1,
        "cycle": cycle,
        "ply_cap": int(plan["round"]["ply_cap"]),
        "games": sources,
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError("existing materialization manifest differs from realized run")
    else:
        _write_new_json(manifest_path, manifest)

    if materialize:
        if batch_out is None:
            raise ValueError("batch_out is required when materialize is enabled")
        completed = subprocess.run(
            [
                str(splendor),
                "m39a-materialize",
                "--plan",
                str(plan_path),
                "--manifest",
                str(manifest_path),
                "--out",
                str(batch_out.resolve()),
            ],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"authoritative materialization failed rc={completed.returncode}: "
                f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
            )
    return {
        "status": "ok",
        "mode": mode,
        "cycle": cycle,
        "games": count,
        "new_game_seconds": elapsed,
        "resident_server": {
            "url": server.url,
            "ready_file": str(server.ready_file),
            **server.identity,
        }
        if server is not None
        else None,
        "manifest": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "batch": str(batch_out.resolve()) if materialize and batch_out else None,
        "batch_sha256": file_sha256(batch_out.resolve())
        if materialize and batch_out
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect one M39A Arena cycle")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--splendor", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["smoke", "complete_cycle"], required=True)
    parser.add_argument("--smoke-games", type=int, default=1)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--no-materialize", action="store_true")
    parser.add_argument("--batch-out", type=Path)
    parser.add_argument(
        "--no-resident-server",
        action="store_true",
        help="spawn a full model per game (legacy mode) instead of one resident server",
    )
    args = parser.parse_args()
    result = collect(
        plan_path=args.plan,
        checkpoint=args.checkpoint,
        checkpoint_sha256=args.checkpoint_sha256,
        checkpoint_hash=args.checkpoint_hash,
        cycle=args.cycle,
        catalog_path=args.catalog,
        splendor=args.splendor,
        out_dir=args.out_dir,
        mode=args.mode,
        smoke_games=args.smoke_games,
        device=args.device,
        materialize=not args.no_materialize,
        batch_out=args.batch_out,
        resident_server=not args.no_resident_server,
    )
    print(json.dumps(result, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
