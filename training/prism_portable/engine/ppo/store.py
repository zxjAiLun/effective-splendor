"""Single-writer, content-addressed checkpoints with one atomic commit pointer.

Only trusted LOCAL torch payloads may be loaded. Hashes detect accidental
corruption, not a malicious author who can replace both data and manifests.
Process-crash atomicity has dedicated engineering tests; universal power-loss durability is not promised.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path

import torch

from ..io import _atomic_write, read_json
from .contract import exact, integer, sha


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class CommitStore:
    def __init__(self, directory, identity, *, max_bytes=None):
        self.root = Path(directory)
        self.identity = sha(identity, "run identity")
        self._held = False
        self.max_bytes = max_bytes
        self._used_bytes = None

    @contextmanager
    def lock(self):
        if self._held:
            raise RuntimeError("nested writer lock")
        self.root.mkdir(parents=True, exist_ok=True)
        stream = (self.root / "writer.lock").open("a+b")
        acquired = False
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = self._held = True
            yield self
        except OSError as exc:
            if not acquired:
                raise RuntimeError("run already has a writer") from exc
            raise
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_UN)
                self._held = False
            stream.close()

    def _require_lock(self):
        if not self._held:
            raise RuntimeError("mutation requires writer lock")

    def _check_space(self, additional):
        if self.max_bytes is not None:
            if self._used_bytes is None:
                self._used_bytes = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            if self._used_bytes + additional > self.max_bytes:
                raise ValueError('artifact storage budget exceeded')

    def _write(self, path, data):
        previous = path.stat().st_size if path.exists() else 0
        additional = len(data) - previous
        self._check_space(additional)
        try:
            _atomic_write(path, lambda stream: stream.write(data))
        except BaseException:
            self._used_bytes = None
            raise
        if self._used_bytes is not None:
            self._used_bytes += additional

    def _put(self, folder, data, suffix):
        self._require_lock()
        digest = hashlib.sha256(data).hexdigest()
        path = self.root / folder / (digest + suffix)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("content-addressed artifact is corrupt")
        else:
            self._write(path, data)
        return digest

    def _get(self, folder, digest, suffix):
        sha(digest, "artifact hash")
        path = self.root / folder / (digest + suffix)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("artifact hash mismatch")
        return data

    def put_json(self, value):
        return self._put("objects", json_bytes(value), ".json")

    def get_json(self, digest):
        from ..io import parse_json
        return parse_json(self._get("objects", digest, ".json").decode("utf-8"))

    def put_payload(self, payload):
        stream = io.BytesIO()
        torch.save(payload, stream)
        return self._put("objects", stream.getvalue(), ".pt")

    def get_payload(self, digest):
        # Never unpickle an unchecked filename supplied by data/sidecars.
        return torch.load(io.BytesIO(self._get("objects", digest, ".pt")), map_location="cpu", weights_only=False)

    def head(self):
        path = self.root / "HEAD.json"
        if not path.exists():
            return None
        value = read_json(path)
        exact(value, {"format", "identity", "commit"}, "head")
        if value["format"] != "prism-ppo-head-v1" or value["identity"] != self.identity:
            raise ValueError("run identity/head mismatch")
        return sha(value["commit"], "commit hash")

    def load(self):
        from ..io import parse_json
        head = self.head()
        if head is None:
            return None, None
        cursor, seen, expected_sequence, head_record = head, set(), None, None
        while cursor is not None:
            if cursor in seen:
                raise ValueError("cyclic commit chain")
            seen.add(cursor)
            record = parse_json(self._get("commits", cursor, ".json").decode("utf-8"))
            exact(record, {"format", "identity", "sequence", "parent", "payload"}, "commit")
            if record["format"] != "prism-ppo-commit-v1" or record["identity"] != self.identity:
                raise ValueError("commit identity mismatch")
            integer(record["sequence"], 0, 2**63 - 1, "sequence")
            if expected_sequence is not None and record["sequence"] != expected_sequence:
                raise ValueError("broken commit sequence")
            if (record["parent"] is None) != (record["sequence"] == 0):
                raise ValueError("broken commit ancestry")
            path = self.root / "objects" / (record["payload"] + ".pt")
            if not path.exists():
                raise ValueError("missing commit payload object")
            if head_record is None:
                head_record = record
            expected_sequence = record["sequence"] - 1
            cursor = record["parent"]
        return head, self.get_payload(head_record["payload"])

    def commit(self, payload, *, expected_parent, fault=None):
        self._require_lock()
        actual = self.head()
        if actual != expected_parent:
            raise ValueError("stale writer: parent changed")
        sequence = 0
        if actual is not None:
            from ..io import parse_json
            record = parse_json(self._get("commits", actual, ".json").decode("utf-8"))
            sequence = record["sequence"] + 1
        blob = self.put_payload(payload)
        if fault:
            fault("payload_written")
        record = {"format": "prism-ppo-commit-v1", "identity": self.identity,
                  "sequence": sequence, "parent": actual, "payload": blob}
        digest = self._put("commits", json_bytes(record), ".json")
        if fault:
            fault("commit_written")
        pointer = {"format": "prism-ppo-head-v1", "identity": self.identity, "commit": digest}
        self._write(self.root / 'HEAD.json', json_bytes(pointer))
        if fault:
            fault("head_published")
        return digest
