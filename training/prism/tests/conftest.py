"""Every generated dataset/checkpoint lives exclusively in pytest tmp_path."""

import json

import numpy as np
import pytest
import torch

from training.prism.data import FILES
from training.prism.io import sha256_file, write_json
from training.prism.model import ACTION_SCHEMA, OBS_SCHEMA

CATALOG = "prism-test-catalog-only"


@pytest.fixture(scope="session", autouse=True)
def cpu_threads():
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False


def make_state(seed=1, entities=3, actions=4):
    rng = np.random.default_rng(seed)
    return {"entities": rng.normal(0, 0.25, (entities, 96)).astype(np.float32),
            "actions": rng.normal(0, 0.25, (actions, 80)).astype(np.float32),
            "targets": (np.arange(actions, dtype=np.int32) % (entities + 1)) - 1}


@pytest.fixture
def dataset_factory(tmp_path):
    def make(name="dataset", train_states=7, val_states=5):
        root = tmp_path / name
        root.mkdir()
        manifest = {"format": "prism-dataset-v1", "observation_schema": OBS_SCHEMA,
                    "action_schema": ACTION_SCHEMA, "catalog_fingerprint": CATALOG,
                    "entity_dim": 96, "action_dim": 80, "sources": [], "splits": {}}
        for split, n, seed in (("train", train_states, 101), ("val", val_states, 105)):
            directory = root / split
            directory.mkdir()
            eo, ao = [0], [0]
            handles = {filename: (directory / filename).open("wb") for filename in FILES}
            try:
                for i in range(n):
                    state = make_state(seed + i, 1 + i % 4, 1 + i % 7)
                    state["entities"].astype("<f4").tofile(handles["entities.f32"])
                    state["actions"].astype("<f4").tofile(handles["actions.f32"])
                    state["targets"].astype("<i4").tofile(handles["targets.i32"])
                    np.array([i % len(state["actions"])], dtype="<u4").tofile(handles["chosen.u32"])
                    np.array([(i % 3) * 0.5], dtype="<f4").tofile(handles["outcomes.f32"])
                    eo.append(eo[-1] + len(state["entities"]))
                    ao.append(ao[-1] + len(state["actions"]))
                    row = {"seed": seed, "ply": i, "actor": i % 2, "observation_hash": "provenance",
                           "chosen_action": {"Pass": None}, "future_secret": "never a model input"}
                    handles["rows.jsonl"].write((json.dumps(row) + "\n").encode())
                np.array(eo, dtype="<u8").tofile(handles["entity_offsets.u64"])
                np.array(ao, dtype="<u8").tofile(handles["action_offsets.u64"])
            finally:
                for handle in handles.values():
                    handle.close()
            manifest["splits"][split] = {"games": 1, "states": n, "entities": eo[-1], "actions": ao[-1],
                                         "hashes": {filename: sha256_file(directory / filename) for filename in FILES}}
            manifest["sources"].append({"seed": seed, "path": "synthetic-test-only.json", "sha256": "0" * 64,
                                        "split": split, "steps": n})
        write_json(root / "manifest.json", manifest)
        return root
    return make
