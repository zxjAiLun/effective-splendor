"""Local authenticated, bounded, single-threaded NDJSON behavior service."""
import argparse
import hmac
import json
import socketserver

import torch

from ..io import parse_json, sha256_file
from .contract import MAX_MESSAGE_BYTES, integer, sha, text, validate_request
from .runtime import configure
from .sampling import Behavior


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(30)
        try:
            data = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
            if not data.endswith(b"\n") or len(data) > MAX_MESSAGE_BYTES:
                raise ValueError("invalid message length/framing")
            request = parse_json(data.decode("utf-8"))
            validate_request(request, authenticated=True)
            if not hmac.compare_digest(request["token"].encode("utf-8"), self.server.token.encode("utf-8")):
                raise ValueError("authentication failed")
            request = {key: value for key, value in request.items() if key != "token"}
            response = self.server.behavior.sample(request)
            output = json.dumps(response, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(output) > MAX_MESSAGE_BYTES:
                raise ValueError("response exceeds limit")
        except (ValueError, TypeError, KeyError, UnicodeError, OSError, RuntimeError):
            # Never serialize the request/token or exception containing user data.
            output = b'{"error":"request rejected"}\n'
        try:
            self.wfile.write(output)
            self.wfile.flush()
        except OSError:
            pass


class BehaviorServer(socketserver.TCPServer):
    allow_reuse_address = False

    def __init__(self, address, behavior, token):
        if address[0] != "127.0.0.1":
            raise ValueError("behavior server must bind 127.0.0.1")
        integer(address[1], 0, 65535, "port")
        self.token = text(token, "token")
        self.behavior = behavior
        super().__init__(address, Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="trusted local .pt snapshot")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--cpu-threads", type=int, required=True)
    args = parser.parse_args(argv)
    sha(args.sha256, "snapshot sha256")
    if sha256_file(args.snapshot) != args.sha256:
        raise ValueError("snapshot file hash mismatch")
    runtime = configure(args.device, args.cpu_threads)
    payload = torch.load(args.snapshot, map_location="cpu", weights_only=False)
    behavior = Behavior.from_payload(payload, runtime=runtime)
    with BehaviorServer(("127.0.0.1", args.port), behavior, args.token) as server:
        print(json.dumps({"endpoint": f"127.0.0.1:{server.server_address[1]}", "behavior_id": behavior.identity}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
