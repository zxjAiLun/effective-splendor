"""Stream a Linux history directory to private ModelScope and verify readback.

The compressed tar stream is written directly into bounded byte shards.  Each
shard is uploaded and discarded before the next one is built, so this script
never assembles a second full archive on the source volume.  Source deletion is
available only after a fresh ModelScope client has downloaded and hashed every
shard and the reconstructed pack byte stream.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping


REPO = "sparxie1/test1005"
REPO_TYPE = "dataset"
DEFAULT_SHARD_BYTES = 128 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
UPLOAD_ATTEMPTS = 6
UPLOAD_EPISODE_SECONDS = 600
DEFAULT_TASK_DEADLINE_SECONDS = 6 * 60 * 60
DEFAULT_TASK_CPU_SECONDS = 30000
DEFAULT_TASK_RSS_MIB = 1536
FORMAT = "prism-remote-history-archive-v1"


class ArchiveError(RuntimeError):
    """A validation or integrity check failed."""


class _TaskBudget:
    """Finite wall, cumulative CPU, and aggregate RSS budget for one archive."""

    def __init__(self, wall_seconds: int, cpu_seconds: int, rss_mib: int) -> None:
        if min(wall_seconds, cpu_seconds, rss_mib) <= 0:
            raise ArchiveError("task deadline and CPU/RSS limits must be positive")
        self.started = time.monotonic()
        self.deadline = self.started + wall_seconds
        self.cpu_limit = cpu_seconds
        self.rss_limit = rss_mib * 1024 * 1024
        self.peak_rss = 0
        self.cpu_seconds = 0.0

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    @staticmethod
    def _rss(pid: int) -> int:
        try:
            with open(f"/proc/{pid}/status", "r", encoding="ascii") as stream:
                lines=stream.readlines()
                for line in lines:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
                if any(line.startswith('State:') and line.split()[1] in ('Z','X') for line in lines):
                    return 0
            # Linux may release an exiting child's mm before changing State
            # to Z. /proc/stat still exposes its actual resident page count.
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = raw[raw.rfind(")") + 2:].split()
            pages = int(fields[21])
            if pages < 0:
                raise ValueError("negative RSS page count")
            return pages * os.sysconf("SC_PAGE_SIZE")
        except (FileNotFoundError, ProcessLookupError):
            return 0
        except (OSError, ValueError, IndexError) as error:
            raise ArchiveError("cannot measure task RSS; stopping within resource contract") from error
        raise ArchiveError("Linux VmRSS measurement is unavailable")

    @staticmethod
    def _cpu() -> float:
        try:
            import resource
            own = resource.getrusage(resource.RUSAGE_SELF)
            child = resource.getrusage(resource.RUSAGE_CHILDREN)
            return own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime
        except (ImportError, AttributeError, OSError) as error:
            raise ArchiveError("cumulative CPU measurement is unavailable") from error

    @staticmethod
    def _cpu_pid(pid: int) -> float:
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = raw[raw.rfind(")") + 2:].split()
            ticks = int(fields[11]) + int(fields[12])
            return ticks / os.sysconf("SC_CLK_TCK")
        except (FileNotFoundError, ProcessLookupError):
            return 0.0
        except (OSError, ValueError, IndexError, ZeroDivisionError) as error:
            raise ArchiveError("cannot measure upload worker CPU; stopping within resource contract") from error

    def check(self, child_pid: int | None = None) -> None:
        if self.remaining() <= 0:
            raise ArchiveError("whole-task wall deadline exhausted")
        self.cpu_seconds = self._cpu()
        if child_pid is not None:
            self.cpu_seconds += self._cpu_pid(child_pid)
        if self.cpu_seconds >= self.cpu_limit:
            raise ArchiveError("whole-task cumulative CPU limit exhausted")
        rss = self._rss(os.getpid())
        if child_pid is not None:
            rss += self._rss(child_pid)
        self.peak_rss = max(self.peak_rss, rss)
        if rss > self.rss_limit:
            raise ArchiveError("whole-task aggregate RSS limit exceeded")

    def receipt(self) -> dict[str, Any]:
        self.check()
        return {
            "wall_seconds": round(time.monotonic() - self.started, 3),
            "cpu_seconds": round(self.cpu_seconds, 3),
            "peak_observed_rss_bytes": self.peak_rss,
            "limits": {
                "wall_seconds": round(self.deadline - self.started),
                "cpu_seconds": self.cpu_limit,
                "aggregate_rss_bytes": self.rss_limit,
            },
        }


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(HASH_CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _stat_signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns if os.name != "nt" else 0,
        info.st_uid,
        info.st_gid,
    )


def _kind(info: os.stat_result, name: str) -> str:
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    if stat.S_ISLNK(info.st_mode):
        raise ArchiveError(f"symlink refused in source tree: {name}")
    raise ArchiveError(f"special file refused in source tree: {name}")


def _canonical_source(value: str | os.PathLike[str]) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise ArchiveError("source path must be absolute")
    normalized = Path(os.path.abspath(raw))
    try:
        resolved = raw.resolve(strict=True)
        info = raw.lstat()
    except OSError as error:
        raise ArchiveError("source path is missing or inaccessible") from error
    if resolved != normalized or stat.S_ISLNK(info.st_mode):
        raise ArchiveError("source path or one of its parents is a symlink")
    if not stat.S_ISDIR(info.st_mode) or resolved == Path(resolved.anchor):
        raise ArchiveError("source must be a non-root directory")
    try:
        parent_info = resolved.parent.stat()
    except OSError as error:
        raise ArchiveError("source parent is inaccessible") from error
    if parent_info.st_dev != info.st_dev:
        raise ArchiveError("source root is a mount boundary; choose a directory inside it")
    return resolved


def _canonical_output(value: str | os.PathLike[str], source: Path) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    parent = raw.parent.resolve(strict=True)
    output = parent / raw.name
    if output == source or source in output.parents:
        raise ArchiveError("manifest output must be outside the source tree")
    if output.exists() or output.is_symlink():
        raise ArchiveError("manifest output already exists")
    return output


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_work_dir(value: str | os.PathLike[str] | None, source: Path) -> tuple[Path, bool]:
    owned = value is None
    if owned:
        work = Path(tempfile.mkdtemp(prefix="prism-history-archive-"))
    else:
        raw = Path(value)
        if not raw.is_absolute():
            raw = Path.cwd() / raw
        raw.mkdir(parents=True, exist_ok=True)
        if raw.is_symlink():
            raise ArchiveError("work directory cannot be a symlink")
        work = raw.resolve(strict=True)
    if _inside(source, work) or work == source:
        raise ArchiveError("work directory must be outside the source tree")
    return work, owned


def _relative_name(path: Path, root: Path) -> str:
    if path == root:
        return "."
    name = path.relative_to(root).as_posix()
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or "\\" in name:
        raise ArchiveError("unsafe source member path")
    return name


def _check_resolved_member(root: Path, path: Path, name: str) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ArchiveError(f"source member disappeared: {name}") from error
    if not _inside(root, resolved):
        raise ArchiveError(f"source member escaped its root: {name}")


def _walk_source(root: Path) -> Iterator[tuple[str, Path, os.stat_result, str]]:
    """Yield a deterministic, symlink-free tree without following links."""
    root_info = root.lstat()
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ArchiveError("source root changed type")
    root_dev = root_info.st_dev

    def visit(directory: Path, relative: str) -> Iterator[tuple[str, Path, os.stat_result, str]]:
        _check_resolved_member(root, directory, relative)
        before = directory.lstat()
        if not stat.S_ISDIR(before.st_mode) or before.st_dev != root_dev:
            raise ArchiveError(f"source directory changed or crossed a mount: {relative}")
        yield relative, directory, before, "directory"
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise ArchiveError(f"cannot enumerate source directory: {relative}") from error
        for entry in entries:
            path = directory / entry.name
            name = entry.name if relative == "." else relative + "/" + entry.name
            _check_resolved_member(root, path, name)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ArchiveError(f"cannot stat source member: {name}") from error
            if os.name == "nt" and info.st_dev == 0:
                info = path.lstat()
            member_kind = _kind(info, name)
            if info.st_dev != root_dev:
                raise ArchiveError(f"source member crosses a mount: {name}")
            if member_kind == "directory":
                yield from visit(path, name)
            else:
                yield name, path, info, member_kind
        after = directory.lstat()
        if _stat_signature(before) != _stat_signature(after):
            raise ArchiveError(f"source directory changed while scanning: {relative}")

    yield from visit(root, ".")


def _open_regular(path: Path, expected: os.stat_result) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ArchiveError(f"cannot safely open source file: {path.name}") from error
    stream = os.fdopen(descriptor, "rb")
    current = os.fstat(stream.fileno())
    if not stat.S_ISREG(current.st_mode) or _stat_signature(current) != _stat_signature(expected):
        stream.close()
        raise ArchiveError(f"source file changed before read: {path.name}")
    return stream


def _hash_source_file(path: Path, expected: os.stat_result, budget: _TaskBudget | None = None) -> str:
    digest = hashlib.sha256()
    with _open_regular(path, expected) as stream:
        while True:
            block = stream.read(HASH_CHUNK_BYTES)
            if not block:
                break
            if budget is not None:
                budget.check()
            digest.update(block)
        if _stat_signature(os.fstat(stream.fileno())) != _stat_signature(expected):
            raise ArchiveError(f"source file changed while hashing: {path.name}")
    try:
        after = path.lstat()
    except OSError as error:
        raise ArchiveError(f"source file disappeared while hashing: {path.name}") from error
    if _stat_signature(after) != _stat_signature(expected):
        raise ArchiveError(f"source file changed while hashing: {path.name}")
    return digest.hexdigest()


def _record(name: str, info: os.stat_result, member_kind: str, sha256: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": name,
        "kind": member_kind,
        "size": info.st_size if member_kind == "file" else 0,
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns if os.name != "nt" else 0,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "device": info.st_dev,
        "inode": info.st_ino,
    }
    if sha256 is not None:
        result["sha256"] = sha256
    return result


def _write_member_manifest(root: Path, output: Path, budget: _TaskBudget | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    members = 0
    raw_bytes = 0
    with output.open("xb") as stream:
        for name, path, info, member_kind in _walk_source(root):
            if budget is not None:
                budget.check()
            member_hash = _hash_source_file(path, info, budget) if member_kind == "file" else None
            row = _record(name, info, member_kind, member_hash)
            encoded = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            stream.write(encoded)
            digest.update(encoded)
            members += 1
            if member_kind == "file":
                raw_bytes += info.st_size
        stream.flush()
        os.fsync(stream.fileno())
    return {"sha256": digest.hexdigest(), "bytes": output.stat().st_size, "members": members, "raw_file_bytes": raw_bytes}


def _expected_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ArchiveError(f"invalid member manifest line {line_number}") from error
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise ArchiveError(f"invalid member manifest record at line {line_number}")
            yield row


def _same_record(actual: dict[str, Any], expected: dict[str, Any], include_hash: bool = True) -> bool:
    keys = ("path", "kind", "size", "mode", "mtime_ns", "ctime_ns", "uid", "gid", "device", "inode")
    if any(actual.get(key) != expected.get(key) for key in keys):
        return False
    return not include_hash or actual.get("sha256") == expected.get("sha256")


def _same_renamed_root(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Allow rename-induced root ctime only when the directory inode is proven unchanged."""
    keys = ("path", "kind", "size", "mode", "mtime_ns", "uid", "gid", "device", "inode")
    return (actual.get("path") == "." and expected.get("path") == "." and
            actual.get("device") == expected.get("device") and
            actual.get("inode") == expected.get("inode") and
            all(actual.get(key) == expected.get(key) for key in keys))


def _verify_source(root: Path, member_manifest: Path, expected_summary: Mapping[str, Any],
                   budget: _TaskBudget | None = None) -> None:
    expected_iter = _expected_rows(member_manifest)
    sentinel = object()
    count = 0
    raw_bytes = 0
    for name, path, info, member_kind in _walk_source(root):
        if budget is not None:
            budget.check()
        expected = next(expected_iter, sentinel)
        if expected is sentinel:
            raise ArchiveError("source gained members after archive inventory")
        actual = _record(name, info, member_kind)
        root_matches = name == "." and _same_renamed_root(actual, expected)
        if not root_matches and not _same_record(actual, expected, include_hash=False):
            raise ArchiveError(f"source metadata drifted after inventory: {name}")
        if member_kind == "file":
            actual["sha256"] = _hash_source_file(path, info, budget)
            if actual["sha256"] != expected.get("sha256"):
                raise ArchiveError(f"source content drifted after inventory: {name}")
            raw_bytes += info.st_size
        count += 1
    if next(expected_iter, sentinel) is not sentinel:
        raise ArchiveError("source lost members after archive inventory")
    if count != expected_summary["members"] or raw_bytes != expected_summary["raw_file_bytes"]:
        raise ArchiveError("source inventory totals changed")


class _HashingReader:
    def __init__(self, stream: Any, budget: _TaskBudget | None = None) -> None:
        self.stream = stream
        self.budget = budget
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        if self.budget is not None:
            self.budget.check()
        self.digest.update(block)
        self.bytes_read += len(block)
        return block


class _ShardedWriter:
    """A seek-free output that uploads bounded byte parts without staging them."""

    def __init__(self, shard_bytes: int, on_shard: Callable[[bytes, dict[str, Any]], None],
                 budget: _TaskBudget | None = None) -> None:
        if shard_bytes < 1:
            raise ArchiveError("shard size must be positive")
        self.shard_bytes = shard_bytes
        self.on_shard = on_shard
        self.budget = budget
        self.pack_digest = hashlib.sha256()
        self.pack_bytes = 0
        self.shards: list[dict[str, Any]] = []
        self._buffer = bytearray()
        self._shard_digest: Any = None
        self._shard_bytes = 0
        self._closed = False

    def writable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pack_bytes

    def _finish_part(self) -> None:
        if not self._buffer:
            return
        row = {"index": len(self.shards), "bytes": self._shard_bytes, "sha256": self._shard_digest.hexdigest()}
        self.on_shard(bytes(self._buffer), row)
        self.shards.append(row)
        self._buffer = bytearray()
        self._shard_digest = None
        self._shard_bytes = 0

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("write to closed sharded output")
        if self.budget is not None:
            self.budget.check()
        original = len(data)
        offset = 0
        while offset < original:
            if len(self._buffer) == self.shard_bytes:
                self._finish_part()
            if self._shard_digest is None:
                self._shard_digest = hashlib.sha256()
            room = self.shard_bytes - self._shard_bytes
            take = min(room, original - offset)
            block = memoryview(data)[offset:offset + take]
            self._buffer.extend(block)
            self._shard_digest.update(block)
            self.pack_digest.update(block)
            self._shard_bytes += take
            self.pack_bytes += take
            offset += take
        return original

    def flush(self) -> None:
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._finish_part()
        self._closed = True


def _stream_tar(root: Path, member_manifest: Path, work_dir: Path, shard_bytes: int,
                upload_part: Callable[[bytes, dict[str, Any]], None],
                member_summary: Mapping[str, Any],
                budget: _TaskBudget | None = None) -> tuple[list[dict[str, Any]], str, int, str]:
    writer = _ShardedWriter(shard_bytes, upload_part, budget)
    expected_iter = _expected_rows(member_manifest)
    sentinel = object()
    embedded_manifest_name = f"{root.name}/.__prism_archive_members__.jsonl"
    if (root / ".__prism_archive_members__.jsonl").exists():
        raise ArchiveError("source uses the reserved archive-index path")
    manifest_sha, manifest_bytes = _sha256_file(member_manifest)
    if manifest_sha != member_summary["sha256"] or manifest_bytes != member_summary["bytes"]:
        raise ArchiveError("local member index changed before archive stream")
    try:
        compressed = gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=1, mtime=0)
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            root_info = root.lstat()
            root_tar = tarfile.TarInfo(root.name)
            root_tar.type = tarfile.DIRTYPE
            root_tar.mode = stat.S_IMODE(root_info.st_mode)
            root_tar.uid = root_info.st_uid
            root_tar.gid = root_info.st_gid
            root_tar.mtime = root_info.st_mtime
            root_tar.size = 0
            archive.addfile(root_tar)

            index_info = tarfile.TarInfo(embedded_manifest_name)
            index_info.mode = 0o600
            index_info.uid = os.getuid() if hasattr(os, "getuid") else 0
            index_info.gid = os.getgid() if hasattr(os, "getgid") else 0
            index_info.mtime = 0
            index_info.size = manifest_bytes
            index_digest = hashlib.sha256()

            class IndexReader:
                def __init__(self, stream: Any) -> None:
                    self.stream = stream

                def read(self, size: int = -1) -> bytes:
                    block = self.stream.read(size)
                    index_digest.update(block)
                    return block

            with member_manifest.open("rb") as index_stream:
                archive.addfile(index_info, IndexReader(index_stream))
            if index_digest.hexdigest() != manifest_sha:
                raise ArchiveError("local member index changed while adding to archive")

            for name, path, info, member_kind in _walk_source(root):
                if budget is not None:
                    budget.check()
                if name == ".":
                    expected = next(expected_iter, sentinel)
                    actual = _record(name, info, member_kind)
                    if expected is sentinel or not _same_record(actual, expected, include_hash=False):
                        raise ArchiveError("source root changed while building archive")
                    continue
                expected = next(expected_iter, sentinel)
                if expected is sentinel:
                    raise ArchiveError("source gained members while building archive")
                actual = _record(name, info, member_kind)
                if not _same_record(actual, expected, include_hash=False):
                    raise ArchiveError(f"source metadata drifted while building archive: {name}")
                archive_name = root.name if name == "." else root.name + "/" + name
                tar_info = tarfile.TarInfo(archive_name)
                tar_info.mode = stat.S_IMODE(info.st_mode)
                tar_info.uid = info.st_uid
                tar_info.gid = info.st_gid
                tar_info.mtime = info.st_mtime
                if member_kind == "directory":
                    tar_info.type = tarfile.DIRTYPE
                    tar_info.size = 0
                    archive.addfile(tar_info)
                else:
                    tar_info.size = info.st_size
                    with _open_regular(path, info) as source_stream:
                        reader = _HashingReader(source_stream, budget)
                        archive.addfile(tar_info, reader)
                        if reader.bytes_read != info.st_size or reader.digest.hexdigest() != expected.get("sha256"):
                            raise ArchiveError(f"source content drifted while archiving: {name}")
                        if _stat_signature(os.fstat(source_stream.fileno())) != _stat_signature(info):
                            raise ArchiveError(f"source file changed while archiving: {name}")
        compressed.close()
        if next(expected_iter, sentinel) is not sentinel:
            raise ArchiveError("source lost members while building archive")
        writer.close()
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        raise
    if not writer.shards or writer.pack_bytes == 0:
        raise ArchiveError("archive stream is empty")
    return writer.shards, writer.pack_digest.hexdigest(), writer.pack_bytes, embedded_manifest_name


def _load_keep(path_value: str | os.PathLike[str] | None, source: Path) -> tuple[set[str], str | None]:
    if path_value is None:
        return set(), None
    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or _inside(source, resolved):
            raise ArchiveError("keep manifest must be a regular file outside source")
        if not resolved.is_file():
            raise ArchiveError("keep manifest must be a regular file")
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except ArchiveError:
        raise
    except Exception as error:
        raise ArchiveError("keep manifest is unreadable or invalid JSON") from error
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict) and isinstance(data.get("paths", data.get("keep")), list):
        values = data.get("paths", data.get("keep"))
    else:
        raise ArchiveError("keep manifest must be a JSON path list or contain a paths list")
    kept: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ArchiveError("keep paths must be nonempty relative POSIX paths")
        pure = PurePosixPath(value)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts) or value != pure.as_posix():
            raise ArchiveError("keep path escapes or is not canonical")
        if value in kept:
            raise ArchiveError("duplicate keep path")
        kept.add(value)
    keep_sha, _ = _sha256_file(resolved)
    return kept, keep_sha


def _check_keep_members(keep: set[str], member_manifest: Path) -> None:
    pending = set(keep)
    for row in _expected_rows(member_manifest):
        name = row["path"]
        if name in pending:
            if row.get("kind") != "file":
                raise ArchiveError(f"keep target is not a regular file: {name}")
            pending.remove(name)
    if pending:
        raise ArchiveError("keep manifest names missing source files")


def _row_value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _new_hub() -> Any:
    # HubApi reads the machine's existing ModelScope login.  Never fetch, print,
    # or pass a token through this script.
    try:
        from modelscope_hub import HubApi
    except ImportError as error:
        raise ArchiveError("modelscope_hub is not installed in this environment") from error
    return HubApi()


def _assert_private(api: Any) -> None:
    try:
        visibility = int(api.get_repo(REPO, REPO_TYPE).visibility)
    except Exception as error:
        raise ArchiveError("cannot verify ModelScope repository visibility or access") from error
    if visibility != 1:
        raise ArchiveError("target ModelScope repository is not private")


def _repo_rows(api: Any) -> dict[str, Any]:
    try:
        rows = api.list_repo_files(REPO, REPO_TYPE)
    except Exception as error:
        raise ArchiveError("cannot list target ModelScope repository") from error
    result = {}
    for row in rows:
        path = _row_value(row, "path")
        if isinstance(path, str):
            result[path] = row
    return result


def _validate_prefix(value: str | None) -> str:
    if value is None:
        host = re.sub(r"[^a-zA-Z0-9-]+", "-", os.uname().nodename.lower()).strip("-") or "linux"
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        value = f"history-archive/{host}/{stamp}-{uuid.uuid4().hex[:12]}"
    pure = PurePosixPath(value)
    if (not value or value.startswith("/") or "\\" in value or
            any(part in ("", ".", "..") for part in pure.parts) or
            not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", value)):
        raise ArchiveError("prefix must be a safe relative ModelScope path")
    return value.rstrip("/")


def _ensure_prefix_empty(api: Any, prefix: str) -> None:
    rows = _repo_rows(api)
    if any(name == prefix or name.startswith(prefix + "/") for name in rows):
        raise ArchiveError("ModelScope prefix already contains objects; refusing overwrite")


def _upload_worker_result(error: BaseException | None = None) -> dict[str, Any]:
    if error is None:
        return {"ok": True, "retryable": False, "rate_limit": False, "retry_after": None}
    error_type = type(error).__name__
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    retry_after = None
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            value = headers.get("Retry-After")
            if value is not None:
                retry_after = min(600.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            retry_after = None
    rate_limit = status == 429 or "ratelimit" in error_type.lower() or "rate_limit" in error_type.lower()
    retryable = rate_limit or status in (500, 502, 503, 504) or any(
        marker in error_type.lower() for marker in ("timeout", "connection", "tempor", "serviceunavailable")
    )
    return {
        "ok": False,
        "error_type": error_type,
        "status": status if isinstance(status, int) else None,
        "retryable": bool(retryable),
        "rate_limit": bool(rate_limit),
        "retry_after": retry_after,
    }


def _upload_worker(remote_path: str) -> int:
    """One SDK upload attempt. Payload arrives over stdin; no credentials are logged."""
    import contextlib
    import logging
    logging.disable(logging.CRITICAL)
    payload = sys.stdin.buffer.read()
    try:
        from modelscope_hub import HubApi
        api = HubApi()
        if int(api.get_repo(REPO, REPO_TYPE).visibility) != 1:
            raise ArchiveError("target repository is not private")
        with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink):
            api.upload_file(REPO, REPO_TYPE, payload, remote_path,
                            commit_message="Private Prism history archive", disable_tqdm=True)
        result = _upload_worker_result()
    except BaseException as error:
        result = _upload_worker_result(error)
    sys.stdout.write("PRISM_UPLOAD_RESULT:" + json.dumps(result, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 2


def _download_worker(remote_path: str, expected_sha: str, cache_dir: str) -> int:
    """One SDK download attempt into a unique, bounded per-shard cache."""
    import contextlib
    import logging
    logging.disable(logging.CRITICAL)
    try:
        from modelscope_hub import HubApi
        api = HubApi()
        if int(api.get_repo(REPO, REPO_TYPE).visibility) != 1:
            raise ArchiveError("target repository is not private")
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                downloaded = Path(api.download_file(
                    REPO, REPO_TYPE, remote_path, expected_sha256=expected_sha, cache_dir=cache_dir
                ))
        root = Path(cache_dir).resolve(strict=True)
        if downloaded.is_symlink() or not downloaded.is_file() or not _inside(root, downloaded.resolve(strict=True)):
            raise ArchiveError("download escaped its per-shard cache")
        result = {"ok": True, "path": str(downloaded.resolve(strict=True))}
    except BaseException as error:
        result = _upload_worker_result(error)
        result["ok"] = False
    sys.stdout.write("PRISM_DOWNLOAD_RESULT:" + json.dumps(result, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 2


def _upload_one_process(payload: bytes, remote_path: str, budget: _TaskBudget,
                        timeout_seconds: float) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({
        "MODELSCOPE_UPLOAD_BLOB_MAX_ATTEMPTS": "1",
        "MODELSCOPE_UPLOAD_COMMIT_MAX_ATTEMPTS": "1",
        "MODELSCOPE_UPLOAD_COMMIT_RETRY_TOTAL_WAIT_SECONDS": "0",
        "MODELSCOPE_MAX_RETRIES": "1",
        "MODELSCOPE_RETRY_MAX_TIMES": "1",
        "PYTHONUNBUFFERED": "1",
    })
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--_upload-stdin", remote_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
    )
    writer_error: list[BaseException] = []

    def send_payload() -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
        except BaseException as error:
            writer_error.append(error)

    writer = threading.Thread(target=send_payload, name="modelscope-shard-stdin", daemon=True)
    writer.start()
    deadline = min(time.monotonic() + timeout_seconds, budget.deadline)
    try:
        while process.poll() is None:
            budget.check(process.pid)
            if time.monotonic() >= deadline:
                raise ArchiveError("ModelScope upload attempt reached its bounded timeout")
            time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))
        writer.join(timeout=2)
        if writer.is_alive() or writer_error:
            raise ArchiveError("ModelScope upload payload pipe failed")
        assert process.stdout is not None
        output = process.stdout.read().decode("utf-8", errors="replace")
        result_line = next((line for line in reversed(output.splitlines())
                            if line.startswith("PRISM_UPLOAD_RESULT:")), None)
        if result_line is None:
            raise ArchiveError("ModelScope upload worker returned no bounded status")
        result = json.loads(result_line.split(":", 1)[1])
        return result
    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.stdout is not None:
            process.stdout.close()


def _download_one_process(remote_path: str, expected_sha: str, cache_dir: Path,
                          budget: _TaskBudget, timeout_seconds: float) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({
        "MODELSCOPE_DOWNLOAD_MAX_ATTEMPTS": "1",
        "MODELSCOPE_DOWNLOAD_RETRY_MAX_TIMES": "1",
        "MODELSCOPE_MAX_RETRIES": "1",
        "MODELSCOPE_RETRY_MAX_TIMES": "1",
        "PYTHONUNBUFFERED": "1",
    })
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--_download-one", remote_path,
         expected_sha, str(cache_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
    )
    deadline = min(time.monotonic() + timeout_seconds, budget.deadline)
    try:
        while process.poll() is None:
            budget.check(process.pid)
            if time.monotonic() >= deadline:
                raise ArchiveError("ModelScope download attempt reached its bounded timeout")
            time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))
        assert process.stdout is not None
        output = process.stdout.read().decode("utf-8", errors="replace")
        result_line = next((line for line in reversed(output.splitlines())
                            if line.startswith("PRISM_DOWNLOAD_RESULT:")), None)
        if result_line is None:
            raise ArchiveError("ModelScope download worker returned no bounded status")
        return json.loads(result_line.split(":", 1)[1])
    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()


def _retry_delay(result: Mapping[str, Any], attempt: int) -> float:
    if result.get("rate_limit"):
        delay = result.get("retry_after")
        return float(delay) if delay is not None else min(240.0, 15.0 * (2 ** (attempt - 1)))
    return min(60.0, 3.0 * (2.0 ** (attempt - 1)))


def _upload_bytes_with_retries(payload: bytes, remote_path: str, budget: _TaskBudget) -> dict[str, Any]:
    episode_started = time.monotonic()
    last_result: dict[str, Any] = {"error_type": "unknown"}
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        budget.check()
        episode_remaining = UPLOAD_EPISODE_SECONDS - (time.monotonic() - episode_started)
        timeout = min(episode_remaining, budget.remaining())
        if timeout <= 0:
            break
        result = _upload_one_process(payload, remote_path, budget, timeout)
        result["attempt"] = attempt
        if result.get("ok"):
            return {"attempts": attempt}
        last_result = result
        if not result.get("retryable") or attempt == UPLOAD_ATTEMPTS:
            break
        delay = _retry_delay(result, attempt)
        remaining = min(UPLOAD_EPISODE_SECONDS - (time.monotonic() - episode_started), budget.remaining())
        if remaining <= 0:
            break
        time.sleep(min(float(delay), remaining))
    raise ArchiveError(
        "ModelScope shard upload exhausted its six-attempt/600-second bounded episode "
        f"(last error type: {last_result.get('error_type', 'timeout')})"
    )


def _check_remote_row(row: Any, expected_sha: str, expected_bytes: int, label: str) -> None:
    remote_sha = _row_value(row, "sha256")
    remote_size = _row_value(row, "size")
    if remote_sha != expected_sha or int(remote_size) != expected_bytes:
        raise ArchiveError(f"ModelScope metadata mismatch for {label}")


def _download_verify(api: Any, remote_path: str, expected_sha: str, expected_bytes: int,
                     cache_dir: Path, label: str, stream_hash: Any | None = None,
                     budget: _TaskBudget | None = None, row: Any | None = None) -> dict[str, Any]:
    if row is None:
        row = _repo_rows(api).get(remote_path)
    if row is None:
        raise ArchiveError(f"ModelScope object is missing: {label}")
    _check_remote_row(row, expected_sha, expected_bytes, label)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if budget is None:
        raise ArchiveError("bounded task budget is required for fresh downloads")
    episode_started = time.monotonic()
    last_result: dict[str, Any] = {"error_type": "unknown"}
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        budget.check()
        episode_remaining = UPLOAD_EPISODE_SECONDS - (time.monotonic() - episode_started)
        timeout = min(episode_remaining, budget.remaining())
        if timeout <= 0:
            break
        attempt_cache = cache_dir / f"attempt-{attempt}-{uuid.uuid4().hex[:8]}"
        attempt_cache.mkdir()
        result: dict[str, Any]
        try:
            result = _download_one_process(remote_path, expected_sha, attempt_cache, budget, timeout)
        except ArchiveError as error:
            if "bounded timeout" not in str(error):
                shutil.rmtree(attempt_cache, ignore_errors=True)
                raise
            result = {"ok": False, "retryable": True, "rate_limit": False,
                      "error_type": "TimeoutError"}
        if result.get("ok"):
            downloaded = Path(str(result.get("path", "")))
            try:
                resolved = downloaded.resolve(strict=True)
                if downloaded.is_symlink() or not resolved.is_file() or not _inside(attempt_cache.resolve(), resolved):
                    raise ArchiveError(f"download escaped its per-shard cache: {label}")
                digest = hashlib.sha256()
                size = 0
                with resolved.open("rb") as stream:
                    while True:
                        block = stream.read(HASH_CHUNK_BYTES)
                        if not block:
                            break
                        budget.check()
                        digest.update(block)
                        size += len(block)
                if size != expected_bytes or digest.hexdigest() != expected_sha:
                    raise ArchiveError(f"fresh ModelScope SHA/size mismatch: {label}")
                if stream_hash is not None:
                    with resolved.open("rb") as stream:
                        while True:
                            block = stream.read(HASH_CHUNK_BYTES)
                            if not block:
                                break
                            budget.check()
                            stream_hash.update(block)
                return {"sha256": digest.hexdigest(), "bytes": size, "attempts": attempt}
            finally:
                shutil.rmtree(attempt_cache, ignore_errors=True)
        shutil.rmtree(attempt_cache, ignore_errors=True)
        result["attempt"] = attempt
        last_result = result
        if not result.get("retryable") or attempt == UPLOAD_ATTEMPTS:
            break
        remaining = min(UPLOAD_EPISODE_SECONDS - (time.monotonic() - episode_started), budget.remaining())
        if remaining <= 0:
            break
        time.sleep(min(_retry_delay(result, attempt), remaining))
    raise ArchiveError(
        f"fresh ModelScope download exhausted its six-attempt/600-second episode for {label} "
        f"(last error type: {last_result.get('error_type', 'timeout')})"
    )


def _validate_remote_readback(api: Any, member_summary: Mapping[str, Any],
                              shards: list[dict[str, Any]], pack_sha: str, pack_bytes: int,
                              cache_dir: Path, budget: _TaskBudget | None = None,
                              download_verify_fn: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    _assert_private(api)
    rows = _repo_rows(api)
    pack_digest = hashlib.sha256()
    verified_shards = []
    for shard in shards:
        if budget is not None:
            budget.check()
        remote_path = shard["path"]
        row = rows.get(remote_path)
        if row is None:
            raise ArchiveError("ModelScope shard is missing")
        _check_remote_row(row, shard["sha256"], shard["bytes"], f"shard {shard['index']}")
        result = (download_verify_fn or _download_verify)(
            api, remote_path, shard["sha256"], shard["bytes"],
            cache_dir, f"shard {shard['index']}", pack_digest, budget, row
        )
        if result.get("sha256") != shard["sha256"] or result.get("bytes") != shard["bytes"]:
            raise ArchiveError(f"fresh ModelScope shard SHA/size mismatch: {shard['index']}")
        verified_shards.append({"index": shard["index"], "path": remote_path, **result})
    if pack_digest.hexdigest() != pack_sha or sum(row["bytes"] for row in verified_shards) != pack_bytes:
        raise ArchiveError("fresh reconstructed tar.gz pack SHA/size mismatch")
    return {
        "status": "PASS_FRESH_CLIENT_READBACK",
        "member_manifest": {
            "embedded_path": member_summary["embedded_path"],
            "sha256": member_summary["sha256"],
            "bytes": member_summary["bytes"],
            "members": member_summary["members"],
            "raw_file_bytes": member_summary["raw_file_bytes"],
        },
        "shards": verified_shards,
        "pack": {"sha256": pack_digest.hexdigest(), "bytes": pack_bytes},
        "verified_at": time.time(),
    }


def _assert_no_active_process(root: Path) -> None:
    if not sys.platform.startswith("linux") or not Path("/proc").is_dir():
        raise ArchiveError("Linux /proc process inspection is required before archive or cleanup")
    root_text = str(root)
    own_pid = os.getpid()

    def matches(value: str) -> bool:
        value = value.removesuffix(" (deleted)")
        return value == root_text or value.startswith(root_text + os.sep)

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            process_info = entry.stat()
            if process_info.st_uid != os.getuid():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().split(b"\0")
                arguments = [x.decode("utf-8", errors="surrogateescape") for x in cmdline if x]
                for text in arguments:
                    if matches(text) or ("=" in text and matches(text.split("=", 1)[1])):
                        raise ArchiveError(f"active process {entry.name} references the source tree")
                # OpenSSH intentionally makes ssh-agent non-dumpable, so even
                # container root cannot read its cwd/fds. This exact platform
                # daemon handles authentication keys, not research-tree writes.
                # Keep all other inaccessible same-user processes fail-closed.
                if arguments in (["/usr/bin/ssh-agent", "-s"],
                                 ["/usr/bin/gpg-agent", "--sh", "--daemon"]):
                    continue
                cwd = os.readlink(entry / "cwd")
                if matches(cwd):
                    raise ArchiveError(f"active process {entry.name} uses the source tree")
                for argument in cmdline:
                    text = argument.decode("utf-8", errors="surrogateescape")
                    if matches(text) or ("=" in text and matches(text.split("=", 1)[1])):
                        raise ArchiveError(f"active process {entry.name} references the source tree")
                fd_dir = entry / "fd"
                for descriptor in fd_dir.iterdir():
                    try:
                        target = os.readlink(descriptor)
                    except FileNotFoundError:
                        continue
                    if matches(target):
                        raise ArchiveError(f"active process {entry.name} has an open source file")
            except FileNotFoundError:
                continue
            except PermissionError as error:
                raise ArchiveError(f"cannot inspect same-user process {entry.name}; refusing cleanup") from error
        except (ProcessLookupError, FileNotFoundError):
            continue


def _safe_remove_tree(path: Path, keep: set[str], expected_rows: Iterator[dict[str, Any]],
                      budget: _TaskBudget, relative: str = ".",
                      expected_root: dict[str, Any] | None = None) -> None:
    """Recheck each file immediately before unlinking; never follow symlinks."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ArchiveError("symlink appeared during cleanup; source was not followed")
    if not stat.S_ISDIR(info.st_mode):
        raise ArchiveError("cleanup root changed type")
    expected = expected_root if expected_root is not None else next(expected_rows, None)
    if expected is None or expected.get("path") != relative:
        raise ArchiveError("source member order changed during cleanup")
    root_matches = relative == "." and _same_renamed_root(_record(relative, info, "directory"), expected)
    if not root_matches and not _same_record(_record(relative, info, "directory"), expected, include_hash=False):
        raise ArchiveError(f"source directory identity drifted during cleanup: {relative}")
    with os.scandir(path) as iterator:
        entries = sorted(iterator, key=lambda entry: entry.name)
    for entry in entries:
        budget.check()
        child = path / entry.name
        name = entry.name if relative == "." else relative + "/" + entry.name
        child_info = entry.stat(follow_symlinks=False)
        if os.name == "nt" and child_info.st_dev == 0:
            child_info = child.lstat()
        child_kind = _kind(child_info, name)
        expected_child = next(expected_rows, None)
        if expected_child is None or expected_child.get("path") != name:
            raise ArchiveError(f"source gained or reordered a member during cleanup: {name}")
        if not _same_record(_record(name, child_info, child_kind), expected_child, include_hash=False):
            raise ArchiveError(f"source member identity drifted during cleanup: {name}")
        if child_kind == "directory":
            keep_below = any(item.startswith(name + "/") for item in keep)
            # Keep one inventory cursor. Wrapping it for each sibling directory
            # accumulates generator recursion and fails on large real runs.
            _safe_remove_tree(child, keep if keep_below else set(), expected_rows,
                              budget, name, expected_root=expected_child)
            if not keep_below:
                child.rmdir()
        else:
            actual_hash = _hash_source_file(child, child_info, budget)
            if actual_hash != expected_child.get("sha256"):
                raise ArchiveError(f"source content drifted immediately before cleanup: {name}")
            if name not in keep:
                after_hash = child.lstat()
                if _stat_signature(after_hash) != _stat_signature(child_info):
                    raise ArchiveError(f"source file changed during cleanup verification: {name}")
                child.unlink()
    remaining = {entry.name for entry in os.scandir(path)}
    expected_kept = {
        PurePosixPath(item).relative_to(PurePosixPath(relative)).parts[0]
        for item in keep
        if relative == "." or item.startswith(relative + "/")
    }
    if remaining != expected_kept:
        raise ArchiveError(f"unexpected source entries remain after cleanup pass: {relative}")
    if relative != ".":
        after = path.lstat()
        if (after.st_dev, after.st_ino, after.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
            raise ArchiveError(f"source directory identity changed during cleanup: {relative}")


def _prepend_row(row: dict[str, Any], rows: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield row
    yield from rows


def _cleanup_verified_source(source: Path, member_manifest: Path, member_summary: Mapping[str, Any],
                             keep: set[str], check_processes: Callable[[Path], None],
                             budget: _TaskBudget) -> dict[str, Any]:
    check_processes(source)
    current = source.lstat()
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        raise ArchiveError("delete target changed type")
    quarantine = source.parent / f".{source.name}.archive-delete-{uuid.uuid4().hex}"
    if quarantine.exists() or quarantine.is_symlink():
        raise ArchiveError("cleanup quarantine path already exists")
    try:
        os.rename(source, quarantine)
    except OSError as error:
        raise ArchiveError("cannot isolate exact delete target") from error
    restored = False
    deletion_started = False
    try:
        check_processes(source)
        check_processes(quarantine)
        _verify_source(quarantine, member_manifest, member_summary, budget)
        before_count = int(member_summary["members"])
        before_bytes = int(member_summary["raw_file_bytes"])
        deletion_started = True
        expected_iter = _expected_rows(member_manifest)
        _safe_remove_tree(quarantine, keep, expected_iter, budget)
        if next(expected_iter, None) is not None:
            raise ArchiveError("member inventory has entries not visited during cleanup")
        retained_bytes = 0
        retained_members = {"."}
        for row in _expected_rows(member_manifest):
            if row["path"] in keep:
                retained_bytes += int(row["size"])
                retained_members.add(row["path"])
                parent = PurePosixPath(row["path"]).parent
                while str(parent) not in (".", ""):
                    retained_members.add(parent.as_posix())
                    parent = parent.parent
        if keep:
            if source.exists() or source.is_symlink():
                raise ArchiveError("source path was recreated during cleanup; retained tree remains quarantined")
            os.rename(quarantine, source)
            restored = True
        else:
            quarantine.rmdir()
        return {
            "status": "PASS_SOURCE_CLEANED" if not keep else "PASS_SOURCE_CLEANED_WITH_KEEP_FILES",
            "target": str(source),
            "removed_members": before_count - len(retained_members),
            "removed_file_bytes": before_bytes - retained_bytes,
            "retained_files": sorted(keep),
            "retained_file_bytes": retained_bytes,
        }
    except Exception:
        try:
            expected_iter.close()
        except (UnboundLocalError, AttributeError):
            pass
        if (not restored and not deletion_started and quarantine.exists() and
                not source.exists() and not source.is_symlink()):
            try:
                os.rename(quarantine, source)
            except OSError:
                pass
        elif deletion_started and quarantine.exists():
            raise ArchiveError(f"cleanup stopped after deletion began; inspect preserved quarantine: {quarantine}")
        raise


def _write_json_new(path: Path, value: Mapping[str, Any]) -> str:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".partial-" + uuid.uuid4().hex)
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def archive_history(source: str | os.PathLike[str], *, prefix: str | None = None,
                    keep_manifest: str | os.PathLike[str] | None = None,
                    delete_target: str | os.PathLike[str] | None = None,
                    manifest_out: str | os.PathLike[str] | None = None,
                    members_out: str | os.PathLike[str] | None = None,
                    work_dir: str | os.PathLike[str] | None = None,
                    shard_bytes: int = DEFAULT_SHARD_BYTES,
                    budget: Any | None = None,
                    hub_factory: Callable[[], Any] = _new_hub,
                    process_checker: Callable[[Path], None] = _assert_no_active_process,
                    upload_bytes_fn: Callable[[bytes, str, Any], Mapping[str, Any]] = _upload_bytes_with_retries,
                    download_verify_fn: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    root = _canonical_source(source)
    keep, keep_manifest_sha = _load_keep(keep_manifest, root)
    if delete_target is not None:
        delete_root = _canonical_source(delete_target)
        if delete_root != root:
            raise ArchiveError("delete target must exactly match the canonical source path")
        if keep_manifest is None:
            raise ArchiveError("--keep is required when --delete-target is used")
    if shard_bytes <= 0:
        raise ArchiveError("shard size must be positive")
    if budget is None:
        budget = _TaskBudget(DEFAULT_TASK_DEADLINE_SECONDS, DEFAULT_TASK_CPU_SECONDS, DEFAULT_TASK_RSS_MIB)
    archive_prefix = _validate_prefix(prefix)
    if manifest_out is None:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        manifest_out = root.parent / f"{root.name}.prism-archive-{stamp}-{uuid.uuid4().hex[:8]}.receipt.json"
    output_path = _canonical_output(manifest_out, root)
    if members_out is None:
        members_out = output_path.with_name(output_path.name + ".members.jsonl")
    members_path = _canonical_output(members_out, root)
    if members_path == output_path:
        raise ArchiveError("receipt and member-index paths must differ")
    workspace, owned_workspace = _validate_work_dir(work_dir, root)
    if members_path.exists() or members_path.is_symlink():
        raise ArchiveError("member-index output already exists")
    cache_root = workspace / ("readback-" + uuid.uuid4().hex)
    cache_root.mkdir()
    try:
        budget.check()
        process_checker(root)
        hub = hub_factory()
        _assert_private(hub)
        _ensure_prefix_empty(hub, archive_prefix)
        member_summary = _write_member_manifest(root, members_path, budget)
        _check_keep_members(keep, members_path)
        uploaded_shards: list[dict[str, Any]] = []

        def upload_part(payload: bytes, row: dict[str, Any]) -> None:
            remote = f"{archive_prefix}/shards/part-{row['index']:06d}.tar.gz.part"
            budget.check()
            result = upload_bytes_fn(payload, remote, budget)
            uploaded_shards.append({**row, "path": remote,
                                   "upload_attempts": int(result.get("attempts", 1))})

        shards, pack_sha, pack_bytes, embedded_path = _stream_tar(
            root, members_path, workspace, shard_bytes, upload_part, member_summary, budget
        )
        member_summary["embedded_path"] = embedded_path
        if len(shards) != len(uploaded_shards) or any(
            any(shard.get(key) != uploaded.get(key) for key in ("index", "bytes", "sha256"))
            for shard, uploaded in zip(shards, uploaded_shards)
        ):
            raise ArchiveError("uploaded shard ledger does not match the streamed archive")

        fresh_hub = hub_factory()
        if fresh_hub is hub:
            raise ArchiveError("ModelScope readback must use a fresh client instance")
        readback = _validate_remote_readback(fresh_hub, member_summary,
                                             uploaded_shards, pack_sha, pack_bytes, cache_root, budget,
                                             download_verify_fn)
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "status": "PASS_FRESH_CLIENT_READBACK",
            "repo": REPO,
            "repo_type": REPO_TYPE,
            "prefix": archive_prefix,
            "source_basename": root.name,
            "archive": {
                "format": "continuous-tar-gz-byte-shards-v1",
                "restore": "concatenate shards in index order to one .tar.gz stream, then extract with tar",
                "sha256": pack_sha,
                "bytes": pack_bytes,
                "shard_bytes_target": shard_bytes,
                "shards": uploaded_shards,
            },
            "members": {
                **member_summary,
                "format": "jsonl-one-record-per-source-member-v1",
            },
            "keep": {"paths": sorted(keep), "manifest_sha256": keep_manifest_sha},
            "fresh_readback": readback,
            "created_at": time.time(),
        }
        manifest_remote = archive_prefix + "/manifest.json"
        manifest_uploader = hub_factory()
        if manifest_uploader is hub or manifest_uploader is fresh_hub:
            raise ArchiveError("manifest upload must use a separate ModelScope client")
        _assert_private(manifest_uploader)
        if manifest_remote in _repo_rows(manifest_uploader):
            raise ArchiveError("manifest path already exists; refusing overwrite")
        manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
        manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
        upload_result = upload_bytes_fn(manifest_raw, manifest_remote, budget)
        manifest_reader = hub_factory()
        if any(manifest_reader is item for item in (hub, fresh_hub, manifest_uploader)):
            raise ArchiveError("final manifest readback must use a fresh ModelScope client")
        _assert_private(manifest_reader)
        manifest_rows = _repo_rows(manifest_reader)
        manifest_download = (download_verify_fn or _download_verify)(
            manifest_reader, manifest_remote, manifest_sha, len(manifest_raw),
            cache_root / "manifest", "final archive manifest", budget=budget,
            row=manifest_rows.get(manifest_remote),
        )
        if (manifest_download.get("sha256") != manifest_sha or
                manifest_download.get("bytes") != len(manifest_raw)):
            raise ArchiveError("fresh ModelScope manifest SHA/size mismatch")
        manifest["cleanup"] = {
            "status": "NOT_REQUESTED" if delete_target is None else "PENDING",
            "target": None if delete_target is None else str(root),
        }
        manifest["cloud_manifest"] = {
            "path": manifest_remote,
            "sha256": manifest_sha,
            "bytes": len(manifest_raw),
            "upload_attempts": int(upload_result.get("attempts", 1)),
            "fresh_readback": manifest_download,
        }
        manifest["local_recovery_index"] = str(members_path)
        manifest["local_receipt"] = str(output_path)
        manifest["resource_usage"] = budget.receipt()
        _write_json_new(output_path, manifest)
        if delete_target is not None:
            cleanup = _cleanup_verified_source(root, members_path, member_summary, keep, process_checker, budget)
            manifest["cleanup"] = cleanup
        manifest["resource_usage"] = budget.receipt()
        _replace_json(output_path, manifest)
        return manifest
    finally:
        shutil.rmtree(cache_root, ignore_errors=True)
        if owned_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="absolute Linux directory to archive")
    parser.add_argument("--prefix", help="unique relative ModelScope prefix; defaults to host/time/nonce")
    parser.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)
    parser.add_argument("--keep", dest="keep_manifest", help="JSON manifest of relative files to preserve on cleanup")
    parser.add_argument("--delete-target", help="explicitly repeat --source to authorize cleanup after fresh SHA readback")
    parser.add_argument("--manifest-out", help="local manifest/restore receipt path outside the source tree")
    parser.add_argument("--members-out", help="local per-member SHA index path outside the source tree")
    parser.add_argument("--work-dir", help="temporary workspace outside the source tree")
    parser.add_argument("--deadline-seconds", type=int, default=DEFAULT_TASK_DEADLINE_SECONDS)
    parser.add_argument("--cpu-seconds", type=int, default=DEFAULT_TASK_CPU_SECONDS)
    parser.add_argument("--max-rss-mib", type=int, default=DEFAULT_TASK_RSS_MIB)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--_upload-stdin":
        if len(arguments) != 2:
            return 64
        return _upload_worker(arguments[1])
    if arguments and arguments[0] == "--_download-one":
        if len(arguments) != 4:
            return 64
        return _download_worker(arguments[1], arguments[2], arguments[3])
    args = _parser().parse_args(arguments)
    try:
        if not sys.platform.startswith("linux") or not Path("/proc").is_dir():
            raise ArchiveError("archive/cleanup CLI requires Linux /proc")
        if not 1 <= args.shard_bytes <= DEFAULT_SHARD_BYTES:
            raise ArchiveError("--shard-bytes must be between 1 and 128 MiB")
        budget = _TaskBudget(args.deadline_seconds, args.cpu_seconds, args.max_rss_mib)
        previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, lambda _signum, _frame: (_ for _ in ()).throw(
            ArchiveError("whole-task wall deadline exhausted")))
        signal.setitimer(signal.ITIMER_REAL, args.deadline_seconds)
        result = archive_history(
            args.source,
            prefix=args.prefix,
            keep_manifest=args.keep_manifest,
            delete_target=args.delete_target,
            manifest_out=args.manifest_out,
            members_out=args.members_out,
            work_dir=args.work_dir,
            shard_bytes=args.shard_bytes,
            budget=budget,
        )
    except Exception as error:
        # SDK exception strings may include request details.  Keep diagnostics
        # useful without exposing credentials, headers, or signed URLs.
        print(json.dumps({"status": "FAIL", "error_type": type(error).__name__, "message": str(error)
                          if isinstance(error, ArchiveError) else "operation failed; sensitive SDK detail suppressed"}),
              file=sys.stderr)
        return 1
    finally:
        if "previous_handler" in locals():
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
