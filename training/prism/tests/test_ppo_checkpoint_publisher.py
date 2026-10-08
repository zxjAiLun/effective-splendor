"""Publisher validation and immutable publication, without SSH or games."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import prism_ppo_checkpoint_publisher as publisher
from scripts.prism_ppo_cloud2_controller import load, save
from training.prism.export import export_weights
from training.prism.ppo.model import PPOModel


@pytest.fixture
def export(tmp_path):
    directory = tmp_path / "export"
    directory.mkdir()
    model = PPOModel(style_enabled=False)
    export_weights(model.policy, directory / "weights.json", publisher.CATALOG,
                   provenance={"commit": "a" * 64, "cycle": 1, "not_promoted": True,
                               "sampling": "softmax-t1"})
    return directory


def test_export_requires_complete_matching_identity(export):
    receipt = publisher.validate_export(export, 1)
    assert receipt["cycle"] == 1 and receipt["training_commit"] == "a" * 64
    with pytest.raises(ValueError, match="cycle/manifest"):
        publisher.validate_export(export, 4)
    manifest = load(export / "weights.manifest.json")
    save(export / "weights.manifest.json", dict(manifest, weights_sha256="b" * 64))
    with pytest.raises(ValueError, match="hash/tensor identity"):
        publisher.validate_export(export, 1)


def test_remote_publish_is_idempotent_and_rejects_drift(export, tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    receipt = publisher.validate_export(export, 1)
    receipt["path"] = str(root / "weights" / (receipt["sha256"] + ".json"))
    script = tmp_path / "remote_publish.py"
    script.write_text(publisher.REMOTE_PUBLISH, encoding="utf-8")

    def incoming(name, metadata):
        path = root / name
        path.mkdir()
        shutil.copyfile(export / "weights.json", path / "weights.json")
        shutil.copyfile(export / "weights.manifest.json", path / "manifest.json")
        save(path / "ready.json", metadata)
        return path

    def run(path):
        return subprocess.run([sys.executable, "-B", str(script), str(path), str(root), "c1"],
                              capture_output=True, text=True)

    first = run(incoming("first", receipt))
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == receipt
    second = run(incoming("second", receipt))
    assert second.returncode == 0, second.stderr
    assert load(root / "ready" / "c1.json") == receipt
    third = run(incoming("third", dict(receipt, training_commit="c" * 64)))
    assert third.returncode != 0
    assert load(root / "ready" / "c1.json") == receipt
