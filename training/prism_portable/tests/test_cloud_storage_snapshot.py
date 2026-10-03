"""The exact disappearing-temp-file regression, without executing matches."""
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.prism_cloud_storage_snapshot import storage_bytes


def test_disappearing_atomic_temp_file_does_not_abort(tmp_path):
    stable = tmp_path / 'report.json'
    stable.write_bytes(b'123456')
    vanished = tmp_path / 'replay.json.42.tmp'
    with patch.object(Path, 'rglob', return_value=iter([stable, vanished])):
        assert storage_bytes(tmp_path) == 6


def test_regular_files_counted_and_symlinks_excluded(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/a').write_bytes(b'123')
    (tmp_path / 'b').write_bytes(b'45')
    assert storage_bytes(tmp_path) == 5


def test_other_io_errors_are_not_hidden(tmp_path):
    with patch.object(Path, 'rglob', return_value=iter([tmp_path / 'denied'])), \
         patch.object(Path, 'stat', side_effect=PermissionError('denied')):
        with pytest.raises(PermissionError):
            storage_bytes(tmp_path)
