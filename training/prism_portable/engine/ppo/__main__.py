"""Explicit, bounded PPO infrastructure commands; never launches a match."""
import argparse
import json

from ..io import read_json
from .coordinator import Run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--config", required=True)
    create.add_argument("--weights", required=True)
    create.add_argument("--run", required=True)
    for name in ("status", "pause", "resume", "seal"):
        commands.add_parser(name).add_argument("--run", required=True)
    begin = commands.add_parser("begin")
    begin.add_argument("--run", required=True); begin.add_argument("--schedule", required=True)
    attempt = commands.add_parser("attempt")
    attempt.add_argument("--run", required=True); attempt.add_argument("--job-id", required=True)
    submit = commands.add_parser("submit")
    for name in ("run", "job-id", "executable", "replay", "sidecar"):
        submit.add_argument("--" + name, required=True)
    submit.add_argument("--attempt", required=True, type=int)
    submit.add_argument("--completion", help="mandatory pinned Arena package for v2 runs")
    step = commands.add_parser("step")
    step.add_argument("--run", required=True); step.add_argument("--max-steps", required=True, type=int)
    export = commands.add_parser("export")
    export.add_argument("--run", required=True); export.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = Run.create(args.run, read_json(args.config), args.weights).status()
    else:
        run = Run.open(args.run)
        if args.command == "status":
            result = run.status()
        elif args.command in ("pause", "resume"):
            run.pause(args.command == "pause"); result = run.status()
        elif args.command == "begin":
            result = run.begin_cycle(read_json(args.schedule))
        elif args.command == "attempt":
            result = {"attempt": run.start_attempt(args.job_id)}
        elif args.command == "submit":
            run.submit(args.job_id, args.attempt, executable=args.executable, replay=args.replay,
                       sidecar=args.sidecar, completion=args.completion)
            result = run.status()
        elif args.command == "seal":
            result = {"batch_id": run.seal()}
        elif args.command == "step":
            if not 1 <= args.max_steps <= 10000:
                raise ValueError("explicit max-steps must be in [1,10000]")
            result = []
            for _ in range(args.max_steps):
                update = run.step(); result.append(update)
                if update["stopped"]:
                    break
        else:
            result = run.export(args.output)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
