"""SSH management for persistent DSW arenas; no training or milestone dispatch."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import prism_notebook_arena as arena


def prepare_spec(path, work):
    spec=arena.read(path)
    arena.require(spec.get('format')=='prism-dsw-arena-request-v1','invalid request format')
    engine=Path(spec['engine']).resolve()
    def descriptors(items, candidate):
        result={}
        for key,item in items.items():
            if item.get('kind')=='heuristic':
                arena.require(not candidate,'candidate must be a Prism model')
                result[key]=arena.heuristic(engine,item['display_name'])
            else:
                result[key]=arena.model(item['weights'],item['display_name'],engine,
                    mode=item.get('mode','sample'),action_seed=spec.get('action_seed',64010001))
        return result
    return arena.prepare(work,engine,spec['metrics_program'],descriptors(spec['candidates'],True),
        descriptors(spec['opponents'],False),spec['seeds'],action_seed=spec.get('action_seed',64010001),
        **spec.get('resources',{}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('profile','prepare','start','status','stop','recover','verify','archive'))
    p.add_argument('--work',type=Path);p.add_argument('--request',type=Path)
    p.add_argument('--force',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.command=='profile':value=arena.resource_profile()
    else:
        p.error('--work is required') if a.work is None else None
        if a.command=='prepare':
            p.error('--request is required') if a.request is None else None
            value=prepare_spec(a.request,a.work)
        elif a.command=='stop':value=arena.stop(a.work,a.force)
        elif a.command=='archive':value=str(arena.export_zip(a.work,a.output))
        else:value=getattr(arena,a.command)(a.work)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
