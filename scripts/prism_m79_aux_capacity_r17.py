"""Bounded owner-capacity probe with a durable terminal receipt on every exit."""
import json
import os
from pathlib import Path
import subprocess
import time

OWNER_LIMIT = 100000000000
REQUIRED_FREE = 20 * 1024**3
TIMEOUT = 180


def admission(reply, now):
    """Distinguish bounded live work from a dead probe or a missing receipt."""
    receipt = reply.get('capacity')
    if receipt:
        if receipt['status'] == 'PASS_OWNER_100GB_CAPACITY':
            return True
        if receipt['status'] != 'CAPACITY_IN_PROGRESS':
            raise ValueError('capacity probe failed: ' + receipt['status'])
    qualifier = reply.get('qualifier') or {}
    if not qualifier.get('alive'):
        raise ValueError('capacity qualifier exited or node changed without a final receipt')
    if now - qualifier['started_at'] >= TIMEOUT:
        raise ValueError('capacity wait exceeded finite 180-second admission window')
    return False


def write_receipt(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def qualify(receipt, workspace='/mnt/workspace', timeout=TIMEOUT):
    began = time.time()
    record = dict(status='CAPACITY_IN_PROGRESS', pid=os.getpid(),
        started_at=began, observed_at=began, timeout_seconds=timeout,
        owner_limit_bytes=OWNER_LIMIT, required_free_bytes=REQUIRED_FREE,
        workspace=workspace, new_games=0)
    write_receipt(receipt, record)
    process = None
    try:
        process = subprocess.Popen(['du', '-sb', workspace],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        record['scan_pid'] = process.pid
        write_receipt(receipt, record)
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode:
            raise ValueError('workspace inventory returned nonzero')
        used = int(stdout.split()[0])
        if used < 0:
            raise ValueError('invalid actual owner usage')
        free = OWNER_LIMIT - used
        record.update(status='PASS_OWNER_100GB_CAPACITY' if free >= REQUIRED_FREE else 'FAIL_OWNER_CAPACITY',
            measured_workspace_bytes=used, free_under_owner_limit_bytes=free,
            source='actual workspace inventory; shared NAS df ignored')
    except subprocess.TimeoutExpired:
        record.update(status='FAIL_CAPACITY_TIMEOUT',
            reason='actual workspace inventory exceeded finite 180-second admission window')
        process.kill()
        try:
            process.wait(timeout=5)
            record['scan_exit_confirmed'] = True
        except subprocess.TimeoutExpired:
            record.update(scan_exit_confirmed=False,
                scan_state='KERNEL_IO_UNINTERRUPTIBLE_OR_EXIT_PENDING')
    except Exception as error:
        record.update(status='FAIL_CAPACITY_PROBE', error_type=type(error).__name__,
            reason=str(error))
    finally:
        record.update(observed_at=time.time(), wall_seconds=time.time()-began)
        write_receipt(receipt, record)
    return record


if __name__ == '__main__':
    print(json.dumps(qualify('/mnt/workspace/splendor-m79-aux-r1/execution-revisions/aux-capacity-r17.json')))
