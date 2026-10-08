import copy
import json

import pytest
import torch

from training.prism import PrismModel, export_weights, load_weights, predict
from training.prism.export import weights_from_dict
from training.prism.io import parse_json, read_json, sha256_file, tensor_identity
from training.prism.parity import main as parity_main
from conftest import CATALOG, make_state


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    path = tmp_path_factory.mktemp("prism-export") / "weights.json"
    torch.manual_seed(1)
    model = PrismModel()
    manifest = export_weights(model, path, CATALOG)
    return model, path, manifest, read_json(path)


def test_json_exact_tensor_identity_and_predictions(exported):
    model, path, manifest, _ = exported
    restored = load_weights(path, expected_catalog_fingerprint=CATALOG)
    assert manifest["weights_sha256"] == sha256_file(path)
    assert manifest["tensor_sha256"] == tensor_identity(model.state_dict()) == tensor_identity(restored.state_dict())
    assert read_json(path.with_suffix(".manifest.json")) == manifest
    for key, tensor in model.state_dict().items():
        assert torch.equal(tensor, restored.state_dict()[key])
    assert predict(model, make_state()) == predict(restored, make_state())


@pytest.mark.parametrize("mutation", ["format", "observation_schema", "action_schema", "catalog_fingerprint",
                                      "hidden_dim", "num_blocks", "entity_dim", "action_dim", "extra",
                                      "missing_key", "extra_key", "shape", "length", "nonfinite", "overflow",
                                      "string", "boolean", "extra_tensor_field"])
def test_strict_weights_reject_malformed(exported, mutation):
    weights = copy.deepcopy(exported[3])
    if mutation in ("format", "observation_schema", "action_schema", "catalog_fingerprint"):
        weights[mutation] = "wrong"
    elif mutation in ("hidden_dim", "num_blocks", "entity_dim", "action_dim"):
        weights[mutation] = 999
    elif mutation == "extra":
        weights["unknown"] = 1
    elif mutation == "missing_key":
        del weights["state_dict"]["encoder.bias"]
    elif mutation == "extra_key":
        weights["state_dict"]["other.weight"] = {"shape": [1], "data": [0]}
    else:
        tensor = weights["state_dict"]["encoder.weight"]
        if mutation == "shape":
            tensor["shape"] = [96, 128]
        elif mutation == "length":
            tensor["data"].pop()
        elif mutation == "extra_tensor_field":
            tensor["dtype"] = "f32"
        else:
            tensor["data"][0] = {"nonfinite": float("nan"), "overflow": 1e300,
                                  "string": "0.0", "boolean": True}[mutation]
    with pytest.raises(ValueError):
        weights_from_dict(weights, expected_catalog_fingerprint=CATALOG)


def test_export_rejects_nonfinite_and_float64(tmp_path):
    model = PrismModel()
    with pytest.raises(ValueError, match="float32"):
        export_weights(model.double(), tmp_path / "bad.json", CATALOG)
    model.float()
    with torch.no_grad():
        model.encoder.weight[0, 0] = torch.inf
    with pytest.raises(ValueError, match="finite"):
        export_weights(model, tmp_path / "bad.json", CATALOG)
    assert not (tmp_path / "bad.json").exists()


@pytest.mark.parametrize("text", ['{"key":1,"key":2}', '{"value":NaN}', '{"value":Infinity}'])
def test_strict_json_parser(text):
    with pytest.raises(ValueError):
        parse_json(text)


def test_streaming_prediction_cli(exported, tmp_path):
    model, weights, _, _ = exported
    source = tmp_path / "fixtures.jsonl"
    dest = tmp_path / "predictions.jsonl"
    state = {key: value.tolist() for key, value in make_state().items()}
    source.write_text(json.dumps(state) + "\n" + json.dumps({"input": state, "seed": 8, "ply": 1, "actor": 0}) + "\n", encoding="utf-8")
    parity_main(["--weights", str(weights), "--input", str(source), "--output", str(dest),
                 "--catalog-fingerprint", CATALOG])
    assert [parse_json(line) for line in dest.read_text().splitlines()] == [predict(model, state)] * 2
