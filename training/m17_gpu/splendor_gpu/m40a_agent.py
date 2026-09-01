"""M40A Arena agent: the M40A sidecar contract over the accepted
M39A agent transport.

Differences from the M39A agent, all frozen by the M40A design:

- the resident server's ready file carries the M40A identity
  (`effective-splendor-m40a-inference-server` v1) with an `arm` field;
- the trajectory sidecar uses the M40A format/version and additionally
  records the arm;
- the recorded value is the M40A readout `V = p_win − p_loss` (the
  server returns it as `values[0]`), and the outcome probabilities are
  recorded for audit;
- sampling, decision-seed derivation, and every protocol check are the
  accepted M39A semantics, imported unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .m39a_agent import (
    ServerProxy as _M39AProxy,
    frozen_draw,
    run_agent_loop,
)
from .m40a_contract import (
    M40A_AGENT_NAME,
    M40A_SERVER_FORMAT,
    M40A_SIDECAR_FORMAT,
    M40A_SIDECAR_VERSION,
)

PROTOCOL_VERSION = "0.5"


class M40AServerProxy(_M39AProxy):
    """The M39A transport with the M40A ready-file identity."""

    def __init__(
        self,
        url: str,
        ready_file: Path,
        *,
        expected_plan_hash: str,
        expected_checkpoint_sha256: str,
        expected_arm: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        # Bypass the M39A __init__ (its format check) and re-do the
        # binding with the M40A identity.
        host_part, _, port_text = url.rpartition(":")
        if not host_part or not port_text.isdigit():
            raise ValueError(f"invalid server url {url!r}; expected host:port")
        self._address = (host_part, int(port_text))
        self._timeout = timeout_seconds
        self._socket = None
        ready = json.loads(ready_file.read_text(encoding="utf-8"))
        if ready.get("format") != M40A_SERVER_FORMAT or int(ready.get("version", 0)) != 1:
            raise ValueError("server ready file is not a v1 M40A inference server")
        for field, expected in (
            ("plan_hash", expected_plan_hash),
            ("checkpoint_sha256", expected_checkpoint_sha256),
        ):
            if ready.get(field) != expected:
                raise ValueError(
                    f"server ready file {field} mismatch: expected {expected!r}, "
                    f"got {ready.get(field)!r}"
                )
        if ready.get("checkpoint_arm") != expected_arm:
            raise ValueError(
                f"server ready file arm mismatch: expected {expected_arm!r}, "
                f"got {ready.get('checkpoint_arm')!r}"
            )
        self.identity = {
            "checkpoint_sha256": ready["checkpoint_sha256"],
            "checkpoint_hash": ready["checkpoint_hash"],
            "checkpoint_cycle": int(ready["checkpoint_cycle"]),
            "checkpoint_arm": ready["checkpoint_arm"],
            "catalog_hash": ready["catalog_hash"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="M40A Arena agent")
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--arm", choices=["A", "B"], required=True)
    parser.add_argument("--game-index", type=int, required=True)
    parser.add_argument("--sidecar-out", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--server-ready", type=Path, required=True)
    parser.add_argument(
        "--action-selection", choices=["categorical", "argmax"], default="categorical"
    )
    args = parser.parse_args()

    proxy = M40AServerProxy(
        args.server_url,
        args.server_ready,
        expected_plan_hash=args.plan_hash,
        expected_checkpoint_sha256=args.checkpoint_sha256,
        expected_arm=args.arm,
    )
    run_agent_loop(
        infer=proxy.infer,
        checkpoint_hash=proxy.identity["checkpoint_hash"],
        checkpoint_cycle=proxy.identity["checkpoint_cycle"],
        checkpoint_sha256=proxy.identity["checkpoint_sha256"],
        plan_hash=args.plan_hash,
        game_index=args.game_index,
        sidecar_out=args.sidecar_out,
        catalog_hash=proxy.identity["catalog_hash"],
        action_selection=args.action_selection,
        close=proxy.close,
        agent_name=M40A_AGENT_NAME,
        sidecar_format=M40A_SIDECAR_FORMAT,
        sidecar_version=M40A_SIDECAR_VERSION,
        extra_sidecar_fields={"arm": args.arm},
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
