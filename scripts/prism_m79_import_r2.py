"""Preserve auxiliary evidence while mapping only host paths in a new import."""
import argparse,inspect,textwrap,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import prism_m79_dual_dispatch as dual


def replace(function,changes):
    source=textwrap.dedent(inspect.getsource(function));namespace=dict(function.__globals__)
    for before,after in changes:
        if source.count(before)!=1:raise ValueError('bound import adapter target drift')
        source=source.replace(before,after)
    exec(compile(source,str(Path(__file__).resolve())+'::'+function.__name__,'exec'),namespace)
    return namespace[function.__name__]


def import_results(archive,receipt=None):
    revision=dual.read_json(ROOT/'migration-r7/revision.json')
    binding=dual.read_json(ROOT/'migration-r7/import-adapter.json')
    if dual.sha_file(Path(__file__))!=binding['adapter_sha256'] or binding['execution_sha256']!=revision['execution_sha256']:
        raise ValueError('independent result importer binding drift')
    if dual.sha_file(ROOT/'scripts/prism_m79_dual_dispatch.py')!=revision['dual_dispatch_sha256']:
        raise ValueError('original dual source changed')
    canon=replace(dual._canonicalize_imported_shard,[
        ('if semantic_config(config, root) != semantic_config(expected_cfg, root):',
         "source_root=Path(config['engine']['program']).parent.parent\n    if semantic_config(config, source_root) != semantic_config(expected_cfg, root):"),
        ('validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)',
         "for name in ('config.json','policy.json','manifest.json','ledger.json'):\n        old=out/name\n        saved=out/('aux-original-'+name)\n        if old.exists() and not saved.exists():saved.write_bytes(old.read_bytes())\n    write_json(config_path,expected_cfg)\n    validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)"),
    ])
    dual._canonicalize_imported_shard=canon
    amended=replace(dual.import_results,[
        ('dest = root / safe_member(name)\n        dest.parent.mkdir(parents=True, exist_ok=True)\n        dest.write_bytes(data)',
         "dest = root / safe_member(name)\n        if name.startswith('evaluation-configs/'):\n            # Keep the pre-dispatch primary config; preserve imported config separately.\n            original=root / REV_DIR_REL / 'aux-original-configs' / Path(name).name\n            original.parent.mkdir(parents=True,exist_ok=True);original.write_bytes(data)\n            if not dest.exists():raise ValueError('primary config was not frozen')\n            continue\n        dest.parent.mkdir(parents=True, exist_ok=True)\n        dest.write_bytes(data)"),
    ])
    result=amended(ROOT,Path(archive),Path(receipt) if receipt else None)
    result['independent_import_adapter_sha256']=dual.sha_file(Path(__file__))
    dual.write_json(ROOT/dual.REV_DIR_REL/'aux-import.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--receipt');a=p.parse_args()
    print(json.dumps(import_results(a.bundle,a.receipt)),flush=True)
