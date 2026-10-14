"""Single-writer storage accounting for an explicitly owned PPO campaign.

Atomic publications are counted at os.replace; only the current external game's
directory and relay file are polled. A restart and each cycle reconcile the whole
tree. This is a sampled storage guard, not a filesystem quota. Historical files
must have no other writer while this adapter owns the campaign.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import time


def inventory(root):
    result = {}
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError('storage tree contains symlink: ' + entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    result[Path(entry.path)] = entry.stat(follow_symlinks=False).st_size
    return result


class CampaignStorage:
    def __init__(self, root, limit):
        started = time.perf_counter()
        self.root = Path(root).resolve()
        self.limit = limit
        self.files = inventory(self.root)
        self.total = sum(self.files.values())
        self.external = set()
        self.external_members = {}
        self.valid = True
        self.metrics = dict(full_scans=1, incremental_checks=0,
                            atomic_publications=0, full_scan_seconds=time.perf_counter()-started,
                            incremental_seconds=0.)
        self.check()

    def contains(self, path):
        return Path(os.path.abspath(path)).is_relative_to(self.root)

    def _update(self, path, size):
        self.total += size - self.files.get(path, 0)
        self.files[path] = size
        for root, members in self.external_members.items():
            if path == root or path.is_relative_to(root):
                members.add(path)

    def refresh(self, path):
        path = Path(os.path.abspath(path))
        if not self.contains(path):
            raise ValueError('external storage path outside campaign')
        if path.is_symlink():
            raise ValueError('external storage symlink')
        # External writers append only to this attempt and one relay file.
        found = inventory(path) if path.is_dir() else ({path: path.stat().st_size} if path.exists() else {})
        old = self.external_members.get(path, {path}).copy()
        for item in old:
            if item not in found:
                self.total -= self.files.pop(item, 0)
        for item, size in found.items():
            self._update(item, size)
        self.external_members[path] = set(found)

    def watch(self, path):
        path = Path(os.path.abspath(path))
        if not self.contains(path):
            raise ValueError('external writer outside owned campaign')
        found = inventory(path) if path.is_dir() else ({path: path.stat().st_size} if path.exists() else {})
        self.external_members[path] = set(found)
        for item, size in found.items():
            self._update(item, size)
        self.external.add(path)

    def unwatch(self, path):
        path = Path(os.path.abspath(path))
        self.refresh(path)
        self.external.discard(path)
        self.external_members.pop(path, None)

    def check(self):
        if not self.valid:
            raise ValueError('storage accounting invalid; restart and reconcile')
        if self.total > self.limit:
            raise ValueError('artifact storage budget exceeded')

    def size(self, root):
        if Path(root).resolve() != self.root:
            raise ValueError('storage guard called for unexpected root')
        started = time.perf_counter()
        for path in self.external:
            self.refresh(path)
        self.check()
        self.metrics['incremental_checks'] += 1
        self.metrics['incremental_seconds'] += time.perf_counter() - started
        return self.total

    def reconcile(self):
        if self.external:
            raise ValueError('full reconciliation requires a quiescent boundary')
        started = time.perf_counter()
        actual = inventory(self.root)
        self.metrics['full_scans'] += 1
        self.metrics['full_scan_seconds'] += time.perf_counter() - started
        if actual != self.files:
            self.valid = False
            differences = [str(p.relative_to(self.root)) for p in actual.keys() | self.files.keys()
                           if actual.get(p) != self.files.get(p)]
            raise ValueError('untracked storage mutation: ' + repr(differences[:10]))
        self.check()
        return self.total

    @contextmanager
    def publications(self):
        original = os.replace
        tracker = self

        def replace(source, destination, *args, **kwargs):
            destination_path = Path(os.path.abspath(destination))
            if not tracker.contains(destination_path):
                return original(source, destination, *args, **kwargs)
            if args or kwargs:
                raise ValueError('dir-fd replacement unsupported by storage guard')
            tracker.check()
            source_path = Path(os.path.abspath(source))
            size = source_path.stat().st_size
            # Reserve temporary + existing destination coexistence before publish.
            if tracker.total + size - tracker.files.get(source_path, 0) > tracker.limit:
                raise ValueError('atomic publication exceeds storage reservation')
            try:
                value = original(source, destination)
                tracker.total -= tracker.files.pop(source_path, 0)
                tracker._update(destination_path, size)
                tracker.metrics['atomic_publications'] += 1
                return value
            except BaseException:
                tracker.valid = False
                raise

        os.replace = replace
        try:
            yield self
        finally:
            os.replace = original


def copy_ledger_for_record(state):
    """record replaces one attempt; it never mutates older nested attempt rows."""
    value = dict(state)
    value['attempts'] = dict(state['attempts'])
    return value


class FrozenFiles:
    """Reject metadata changes after full boundary hashing of trusted inputs."""
    def __init__(self, paths):
        self.files = {Path(p).resolve(): self.stamp(Path(p).resolve()) for p in paths}

    @staticmethod
    def stamp(path):
        s = path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def check(self):
        for path, stamp in self.files.items():
            if self.stamp(path) != stamp:
                raise ValueError('frozen input changed: ' + str(path))
