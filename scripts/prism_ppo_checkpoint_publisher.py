"""Read-only publisher for committed M54 c1/c4/c8 exports to cloud2.

No Run.open(), writer lock, optimizer or games. Strictly validate a complete
32-key export and its manifest; upload unique temporary files, verify remote
SHA256, publish immutable assets, then atomically expose checkpoint ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_ppo_cloud2_controller import load, save

CATALOG = "1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb"
REMOTE_PUBLISH = '''import hashlib,json,os,pathlib,sys
incoming=pathlib.Path(sys.argv[1]); root=pathlib.Path(sys.argv[2]); label=sys.argv[3]
meta=json.loads((incoming/'ready.json').read_text())
manifest=json.loads((incoming/'manifest.json').read_text())
weight=incoming/'weights.json'
assert hashlib.sha256(weight.read_bytes()).hexdigest()==meta['sha256']==manifest['weights_sha256']
assert manifest['provenance']['cycle']==meta['cycle']
assert manifest['provenance']['commit']==meta['training_commit']
assert len(manifest['tensors'])==32
for source,target in [(weight,pathlib.Path(meta['path'])),(incoming/'manifest.json',root/'weights'/(label+'.manifest.json'))]:
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest(), 'immutable asset drift'
    else:
        os.link(source,target)
        if os.name != 'nt': target.chmod(0o444)
ready=root/'ready'/(label+'.json'); ready.parent.mkdir(parents=True,exist_ok=True)
if ready.exists():
    assert json.loads(ready.read_text())==meta, 'immutable ready drift'
else:
    os.link(incoming/'ready.json',ready)
    if os.name != 'nt': ready.chmod(0o444)
for p in incoming.iterdir(): p.unlink()
incoming.rmdir()
print(json.dumps(meta))
'''


def validate_export(directory, cycle):
    from training.prism.export import load_weights
    from training.prism.io import sha256_file, tensor_identity
    path = directory / "weights.json"
    manifest = load(directory / "weights.manifest.json")
    provenance = manifest["provenance"]
    if manifest["format"] != "prism-weights-manifest-v1" or provenance["cycle"] != cycle:
        raise ValueError("export cycle/manifest mismatch")
    if provenance["sampling"] != "softmax-t1" or not provenance["not_promoted"]:
        raise ValueError("export provenance/sampling mismatch")
    if len(provenance["commit"]) != 64 or len(manifest["tensors"]) != 32:
        raise ValueError("export identity/tensor keys")
    model = load_weights(path, expected_catalog_fingerprint=CATALOG)
    if sha256_file(path) != manifest["weights_sha256"] or tensor_identity(model.state_dict()) != manifest["tensor_sha256"]:
        raise ValueError("export hash/tensor identity mismatch")
    return {"sha256": manifest["weights_sha256"], "cycle": cycle, "training_commit": provenance["commit"]}


def command(argv, timeout=180):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} exit {result.returncode}: {result.stderr[-2000:]}")
    return result.stdout


def publish(host, remote_root, directory, cycle, scratch):
    label = f"c{cycle}"
    metadata = validate_export(directory, cycle)
    metadata["path"] = remote_root + "/weights/" + label + "-" + metadata["sha256"] + ".json"
    with tempfile.TemporaryDirectory(prefix="m54-publish-", dir=scratch) as temporary:
        temp = Path(temporary)
        save(temp / "ready.json", metadata)
        (temp / "publish.py").write_text(REMOTE_PUBLISH, encoding="utf-8")
        incoming = remote_root + "/incoming/" + temp.name
        command(["ssh", host, "mkdir -p " + shlex.quote(incoming)])
        for source, name in [(directory / "weights.json", "weights.json"),
                             (directory / "weights.manifest.json", "manifest.json"),
                             (temp / "ready.json", "ready.json"), (temp / "publish.py", "publish.py")]:
            command(["scp", str(source), host + ":" + incoming + "/" + name], timeout=300)
        output = command(["ssh", host, "python3 " + shlex.quote(incoming + "/publish.py") + " " +
                          " ".join(shlex.quote(arg) for arg in (incoming, remote_root, label))])
        if json.loads(output) != metadata:
            raise ValueError("remote publication receipt mismatch")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--host", default="cloud2")
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--wait-seconds", type=int, default=28800)
    args = parser.parse_args()
    state_path = Path(args.state)
    state = load(state_path) if state_path.exists() else {
        "format": "m54-checkpoint-publisher-v1", "campaign": str(Path(args.campaign).resolve()),
        "host": args.host, "remote_root": args.remote_root, "published": {},
        "deadline": time.time() + args.wait_seconds}
    if (state["campaign"], state["host"], state["remote_root"]) != (
            str(Path(args.campaign).resolve()), args.host, args.remote_root):
        raise ValueError("publisher identity drift")
    state["pid"] = os.getpid()
    save(state_path, state)
    try:
        for cycle in (1, 4, 8):
            label = f"c{cycle}"
            if label in state["published"]:
                continue
            directory = Path(args.campaign) / f"cycle-{cycle}-export"
            while not (directory / "weights.manifest.json").is_file():
                if time.time() >= state["deadline"]:
                    raise TimeoutError("committed checkpoint unavailable: " + label)
                time.sleep(10)
            for attempt in range(3):
                try:
                    receipt = publish(args.host, args.remote_root, directory, cycle, os.environ["PI_SCRATCH_DIR"])
                    break
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    state["last_transport_error"] = str(exc)
                    save(state_path, state)
                    if attempt == 2:
                        raise
                    time.sleep(30)
            state["published"][label] = receipt
            save(state_path, state)
            print(json.dumps({"event": "checkpoint_published", "label": label, **receipt}), flush=True)
        state.update(complete=True, finished_at=time.time())
        save(state_path, state)
    except BaseException as exc:
        state.update(complete=False, error=type(exc).__name__ + ": " + str(exc))
        save(state_path, state)
        raise


if __name__ == "__main__":
    main()
