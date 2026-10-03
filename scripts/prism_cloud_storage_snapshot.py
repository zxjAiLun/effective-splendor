"""Race-safe best-effort size of an owned campaign's regular files.

Atomic writers may replace/unlink a temporary file after directory enumeration.
Only disappearance is tolerated; permissions and other I/O failures propagate.
"""
import stat
from pathlib import Path


def storage_bytes(root):
    total = 0
    for path in Path(root).rglob('*'):
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode):
            total += metadata.st_size
    return total
