import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
import unittest
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import prism_remote_history_archive as archive


class FakeBudget:
    def __init__(self):
        self.deadline = time.monotonic() + 21600

    def check(self, child_pid=None):
        return None

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def receipt(self):
        return {"wall_seconds": 0, "cpu_seconds": 0, "peak_observed_rss_bytes": 0,
                "limits": {"wall_seconds": 21600, "cpu_seconds": 30000,
                           "aggregate_rss_bytes": 1536 * 1024 * 1024}}


class FakeHub:
    def __init__(self, objects):
        self.objects = objects

    def get_repo(self, repo, repo_type):
        return SimpleNamespace(visibility=1)

    def list_repo_files(self, repo, repo_type):
        return [SimpleNamespace(path=name, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
                for name, data in self.objects.items()]


class PrismRemoteHistoryArchiveTests(unittest.TestCase):
    def test_cleanup_many_sibling_directories_keeps_one_inventory_cursor(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'history';root.mkdir()
            for number in range(1100):
                folder=root/f'{number:04d}';folder.mkdir();(folder/'raw').write_bytes(b'x')
            (root/'weights.json').write_bytes(b'model')
            index=base/'members.jsonl';archive._write_member_manifest(root,index)
            rows=archive._expected_rows(index)
            archive._safe_remove_tree(root,{'weights.json'},rows,FakeBudget())
            self.assertIsNone(next(rows,None))
            self.assertEqual([p.name for p in root.iterdir()],['weights.json'])
            self.assertEqual((root/'weights.json').read_bytes(),b'model')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'requires Linux process inspection')
    def test_process_exit_during_proc_inventory_is_allowed(self):
        vanished = SimpleNamespace(name='999999', stat=lambda: (_ for _ in ()).throw(FileNotFoundError()))
        with patch.object(Path, 'iterdir', return_value=iter([vanished])):
            archive._assert_no_active_process(Path('/mnt/workspace/ended-history'))

    def test_exiting_child_rss_uses_kernel_page_count(self):
        from unittest.mock import mock_open
        fields = ['R'] + ['0'] * 21
        with patch('builtins.open', mock_open(read_data='State:\tR\n')), \
             patch.object(Path, 'read_text', return_value='123 (python) ' + ' '.join(fields)), \
             patch.object(os, 'sysconf', return_value=4096, create=True):
            self.assertEqual(archive._TaskBudget._rss(123), 0)
            fields[21] = '17'
        with patch('builtins.open', mock_open(read_data='State:\tR\n')), \
             patch.object(Path, 'read_text', return_value='123 (python) ' + ' '.join(fields)), \
             patch.object(os, 'sysconf', return_value=4096, create=True):
            self.assertEqual(archive._TaskBudget._rss(123), 17 * 4096)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'requires a real /proc zombie')
    def test_exited_child_without_vmrss_is_not_a_resource_failure(self):
        child=subprocess.Popen([sys.executable,'-B','-c','pass'])
        try:
            time.sleep(.2)
            self.assertEqual(archive._TaskBudget._rss(child.pid),0)
        finally:
            child.wait(timeout=5)

    def test_stream_tar_uses_gzip_wrapper_and_shards_have_exact_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "history"
            root.mkdir()
            (root / "payload.bin").write_bytes(os.urandom(12 * 1024))
            index = base / "members.jsonl"
            summary = archive._write_member_manifest(root, index)
            pieces = []

            def capture(payload, row):
                self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])
                self.assertEqual(len(payload), row["bytes"])
                pieces.append(payload)

            rows, pack_sha, pack_size, embedded = archive._stream_tar(
                root, index, base, 1024, capture, summary
            )
            packed = b"".join(pieces)
            self.assertGreater(len(rows), 1)
            self.assertEqual(len(packed), pack_size)
            self.assertEqual(hashlib.sha256(packed).hexdigest(), pack_sha)
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(packed)), mode="r:") as tar:
                self.assertEqual(tar.extractfile("history/payload.bin").read(), (root / "payload.bin").read_bytes())
                embedded_index = tar.extractfile(embedded).read()
            self.assertEqual(hashlib.sha256(embedded_index).hexdigest(), summary["sha256"])
            self.assertEqual(json.loads(embedded_index.splitlines()[1])["sha256"],
                             hashlib.sha256((root / "payload.bin").read_bytes()).hexdigest())

    def test_fresh_readback_and_real_rename_cleanup_preserve_keep_file(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "m75-history"
            (root / "models").mkdir(parents=True)
            (root / "reports").mkdir()
            (root / "raw").mkdir()
            (root / "models" / "best.bin").write_bytes(b"model-result")
            (root / "reports" / "final.json").write_text('{"result":"kept"}', encoding="utf-8")
            (root / "raw" / "games.jsonl").write_bytes(b"historical-data" * 128)
            keep_file = base / "keep.json"
            keep_file.write_text(json.dumps(["models/best.bin", "reports/final.json"]), encoding="utf-8")
            before_root = root.lstat()
            expected_root = archive._record(".", before_root, "directory")
            after_root = dict(expected_root, ctime_ns=expected_root["ctime_ns"] + 1)
            self.assertTrue(archive._same_renamed_root(after_root, expected_root))
            self.assertFalse(archive._same_renamed_root(
                dict(after_root, inode=after_root["inode"] + 1), expected_root
            ))
            receipt_path = base / "m75.receipt.json"
            index_path = base / "m75.members.jsonl"
            objects = {}
            hubs = []

            def hub_factory():
                hub = FakeHub(objects)
                hubs.append(hub)
                return hub

            def upload(payload, remote, _budget):
                objects[remote] = bytes(payload)
                return {"attempts": 1}

            def download(_api, remote, expected_sha, expected_bytes, _cache, _label,
                         stream_hash=None, budget=None, row=None):
                payload = objects[remote]
                digest = hashlib.sha256(payload).hexdigest()
                if digest != expected_sha or len(payload) != expected_bytes:
                    raise archive.ArchiveError("simulated fresh readback mismatch")
                if stream_hash is not None:
                    stream_hash.update(payload)
                return {"sha256": digest, "bytes": len(payload)}

            result = archive.archive_history(
                root, prefix="tests/m75", keep_manifest=keep_file, delete_target=root,
                manifest_out=receipt_path, members_out=index_path, work_dir=base / "work",
                shard_bytes=4096, budget=FakeBudget(), hub_factory=hub_factory,
                process_checker=lambda _path: None, upload_bytes_fn=upload,
                download_verify_fn=download,
            )
            self.assertGreaterEqual(len(hubs), 4)
            self.assertEqual(result["cleanup"]["status"], "PASS_SOURCE_CLEANED_WITH_KEEP_FILES")
            self.assertEqual((root / "models" / "best.bin").read_bytes(), b"model-result")
            self.assertEqual((root / "reports" / "final.json").read_text(encoding="utf-8"), '{"result":"kept"}')
            self.assertFalse((root / "raw").exists())
            self.assertTrue(receipt_path.is_file())
            self.assertTrue(index_path.is_file())
            self.assertEqual(result["fresh_readback"]["pack"]["sha256"], result["archive"]["sha256"])
            self.assertTrue(all(hubs[0] is not hub for hub in hubs[1:]))

    def test_readback_mismatch_keeps_source_and_cli_resource_defaults_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "history"
            root.mkdir()
            (root / "data.bin").write_bytes(b"must remain")
            keep_file = base / "keep.json"
            keep_file.write_text(json.dumps(["data.bin"]), encoding="utf-8")
            objects = {}

            def upload(payload, remote, _budget):
                objects[remote] = bytes(payload)
                return {"attempts": 1}

            def corrupt_download(_api, remote, expected_sha, _expected_bytes, _cache, _label,
                                 stream_hash=None, budget=None, row=None):
                wrong = b"X" * len(objects[remote])
                digest = hashlib.sha256(wrong).hexdigest()
                if stream_hash is not None:
                    stream_hash.update(wrong)
                return {"sha256": digest, "bytes": len(wrong)}

            with self.assertRaises(archive.ArchiveError):
                archive.archive_history(
                    root, prefix="tests/tampered", keep_manifest=keep_file, delete_target=root,
                    manifest_out=base / "receipt.json", work_dir=base / "work",
                    shard_bytes=4096, budget=FakeBudget(), hub_factory=lambda: FakeHub(objects),
                    process_checker=lambda _path: None, upload_bytes_fn=upload,
                    download_verify_fn=corrupt_download,
                )
            self.assertEqual((root / "data.bin").read_bytes(), b"must remain")
            args = archive._parser().parse_args(["--source", "/mnt/workspace/history"])
            self.assertEqual(args.deadline_seconds, 21600)
            self.assertEqual(args.cpu_seconds, 30000)
            self.assertEqual(args.max_rss_mib, 1536)
            self.assertEqual(archive.UPLOAD_ATTEMPTS, 6)
            self.assertEqual(archive.UPLOAD_EPISODE_SECONDS, 600)


if __name__ == "__main__":
    unittest.main()
