"""SHA-checked Notebook source/model transport; no secrets or generated replays."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import urllib.request
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def fetch(url,path,expected_sha256):
    path=Path(path).resolve()
    if not url.startswith('https://') or len(expected_sha256)!=64:
        raise ValueError('HTTPS URL and explicit SHA256 required')
    if path.exists():
        if sha(path)!=expected_sha256:raise ValueError('existing input differs from declared SHA')
        return path
    path.parent.mkdir(parents=True,exist_ok=True);partial=path.with_name(path.name+'.download-'+uuid.uuid4().hex)
    with urllib.request.urlopen(url,timeout=60) as response,partial.open('xb') as output:
        total=0
        while True:
            chunk=response.read(1024*1024)
            if not chunk:break
            total+=len(chunk)
            if total>512*1024**2:raise ValueError('download exceeds512MiB')
            output.write(chunk)
    if sha(partial)!=expected_sha256:raise ValueError('downloaded input SHA mismatch; partial retained')
    partial.replace(path);return path


def unpack(bundle,destination,expected_sha256,*,source=False):
    bundle,destination=Path(bundle).resolve(),Path(destination).resolve()
    if sha(bundle)!=expected_sha256:raise ValueError('bundle SHA mismatch')
    with zipfile.ZipFile(bundle) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate archive names')
        if sum(x.file_size for x in z.infolist())>256*1024**2:raise ValueError('expanded bundle exceeds256MiB')
        manifest=json.loads(z.read('manifest.json'))
        expected='prism-notebook-source-bundle-v1' if source else 'prism-notebook-model-bundle-v1'
        if manifest.get('format')!=expected:raise ValueError('bundle kind differs')
        entries=manifest['files']
        if set(names)!=set(entries)|{'manifest.json'}:raise ValueError('archive files differ from manifest')
        for name,digest in entries.items():
            p=PurePosixPath(name);info=z.getinfo(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('unsafe archive member')
            allowed=(name in ('Cargo.toml','Cargo.lock') or p.parts[0] in ('crates','scripts','notebooks','docs')) if source else p.parts[0]=='models'
            if not allowed:raise ValueError('archive member outside declared source/model roots')
            raw=z.read(name)
            if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('member SHA mismatch')
            target=destination/Path(*p.parts)
            if not target.resolve().is_relative_to(destination):raise ValueError('archive target escapes destination')
            if not source and target.exists() and sha(target)!=digest:raise ValueError('refuse conflicting model overwrite')
        # Validate the complete archive before applying an explicit source overlay.
        for name in entries:
            target=destination/Path(*PurePosixPath(name).parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
        destination.mkdir(parents=True,exist_ok=True)
        (destination/('source-bundle-manifest.json' if source else 'model-bundle-manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


def source_bundle(output):
    files={p for p in (ROOT/'crates').rglob('*') if p.is_file() and p.suffix in ('.rs','.toml','.json','.md')
           and not any(x in p.parts for x in ('target','.git'))}
    files.update(ROOT/p for p in ('Cargo.toml','Cargo.lock','scripts/prism_ppo_fixed_eval.py','scripts/prism_match_details.py',
        'scripts/prism_cloud_storage_snapshot.py','scripts/prism_notebook_arena.py','scripts/prism_notebook_report.py',
        'scripts/prism_notebook_bundle.py','scripts/prism_dsw_arena.py','scripts/prism_dsw_manage.sh','scripts/prism_dsw_bootstrap.sh','notebooks/prism_multicore_arena.ipynb','notebooks/requirements-prism-arena.txt',
        'docs/m64-prism-notebook-arena.md','docs/prism/notebook-arena-operations.md'))
    return _pack(output,{str(p.relative_to(ROOT)).replace('\\','/'):p for p in files},'prism-notebook-source-bundle-v1')


def model_bundle(output,models):
    files={};metadata={}
    for name,entry in models.items():
        if not name.replace('-','').replace('_','').isalnum():raise ValueError('unsafe model id')
        p=Path(entry['path']).resolve();v=json.loads(p.read_text('utf-8'))
        if v.get('format')!='prism-weights-v1':raise ValueError('exported Prism JSON required')
        target='models/'+name+'.json';files[target]=p;metadata[name]=dict(path=target,display_name=entry['display_name'],
            sha256=sha(p),catalog_fingerprint=v['catalog_fingerprint'])
    return _pack(output,files,'prism-notebook-model-bundle-v1',models=metadata)


def _pack(output,files,format,**metadata):
    output=Path(output).resolve()
    if output.exists():raise ValueError('refuse replacing a previous bundle')
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest=dict(format=format,files={name:sha(path) for name,path in sorted(files.items())},**metadata)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for name,p in sorted(files.items()):z.write(p,name)
        z.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
    return dict(path=str(output),sha256=sha(output),bytes=output.stat().st_size,files=len(files))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('source','models'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--models',type=Path)
    args=parser.parse_args()
    print(json.dumps(source_bundle(args.output) if args.mode=='source' else model_bundle(args.output,json.loads(args.models.read_text('utf-8'))),indent=2))
