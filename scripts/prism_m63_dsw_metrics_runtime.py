"""Load only three frozen stdlib helpers for saved-replay metrics without Torch.

The original io/contract modules import the training tensor runtime eagerly.
M63 offline profiles need only canonical_hash, exact and integer. Compile those
unchanged function ASTs from the SHA-pinned original files. This deliberately
does not expose tensor, learner or checkpoint operations.
"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

CONFIG_SHA = 'c0d3de5398c724bd502d5c30f5f52ec06a848f7fe2672c28e1086c7730b21550'


def extract_functions(path, names):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'), filename=str(path))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != set(names): raise ValueError('frozen helper inventory mismatch')
    module = types.ModuleType('saved_metrics_helpers')
    module.__dict__.update(hashlib=hashlib, json=json)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


def install(root):
    if importlib.util.find_spec('torch') is not None: return 'original Torch runtime available'
    root = Path(root)
    config_path = root / 'benchmarks/m63-prism-beta-timed-building.config.json'
    raw = config_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA: raise ValueError('metrics runtime original config drift')
    sources = json.loads(raw)['runtime']['source_hashes']
    inventory = {'training.prism_portable.engine.io': ('training/prism_portable/engine/io.py', ['canonical_hash']),
                 'training.prism_portable.engine.ppo.contract': ('training/prism_portable/engine/ppo/contract.py', ['exact', 'integer'])}
    for module_name, (name, functions) in inventory.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != sources[name]:
            raise ValueError('frozen metrics helper source drift: ' + name)
        if module_name in sys.modules: raise ValueError('unexpected preloaded training runtime')
        module = extract_functions(root / name, functions)
        module.__name__, module.__file__ = module_name, str(root / name)
        module.__package__ = module_name.rpartition('.')[0]
        sys.modules[module_name] = module
    return 'stdlib-only exact frozen helper ASTs; training operations unavailable'
