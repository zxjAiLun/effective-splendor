"""Revalidate completed c5 intake metadata in the bound receiver environment.

No game/result/source/policy byte changes. Preserve previous receiver metadata,
and distinguish its runtime from the original auxiliary execution runtime.
"""
from pathlib import Path
import copy
import json
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_completion_r21 as revision,prism_bounded_eval as b

def revalidate():
    revision.verify()
    receipt=read(ROOT/'execution-revisions/aux-development-r12/import.json')
    if receipt['status']!='PASS_SHA_BOUND_DEVELOPMENT_IMPORT' or (receipt['games'],receipt['truncated_games'])!=(255,1):
        raise ValueError('original c5 import identity mismatch')
    archive=ROOT/'execution-revisions/aux-development-r12/results.zip'
    if digest(archive)!=receipt['archive_sha256']:
        raise ValueError('original c5 archive drift')
    rev=revision.REV/'c5-intake'
    with lock(rev/'control'):
        if (rev/'receipt.json').exists():return read(rev/'receipt.json')
        checked=[]
        for start in (17040000,17040032,17040064,17040096):
            label=f'development-curve-c5-parent-{start}';out=ROOT/'evaluation'/label
            manifest=read(out/'manifest.json');ledger=read(out/'ledger.json');cfg=read(out/'config.json');policy=read(out/'policy.json')
            if ledger['execution_state']!='FINISHED' or len(ledger['entries'])!=64 or ledger['manifest_sha256']!=digest(out/'manifest.json'):
                raise ValueError('c5 completion/binding drift')
            if manifest['config_sha256']!=b.fixed.canonical_hash(cfg) or manifest['policy_sha256']!=b.fixed.canonical_hash(policy):
                raise ValueError('c5 config/policy drift')
            if set(manifest['source_sha256'])!=set(b.SOURCES):raise ValueError('source set drift')
            for name,sha in manifest['source_sha256'].items():
                if digest(ROOT/name)!=sha or digest(out/'source'/name)!=sha:raise ValueError('source drift '+name)
            validated=b.arena.validate_arena_config(cfg,out/'config.json');validated['config']=cfg
            b.fixed.check_assets(validated);b.validate_policy(policy,cfg)
            for job in b.legacy.jobs(cfg):
                key=b.fixed._game_key(*job);entry=ledger['entries'][key];directory=b.legacy.game_directory(out,job)
                if entry['state']!='COMPLETED' and entry.get('kind')!='PLY_CAP_TRUNCATED':raise ValueError('unresolved c5 result')
                if entry['evidence_sha256']!=b.evidence(directory):raise ValueError('c5 evidence drift')
                b.validate_resources(read(directory/'process-result.json'),b.rollout_command(validated,policy,directory))
                result=b.validate_artifacts(directory,cfg,job,policy['ply_cap'])
                if {k:v for k,v in entry.items() if k!='evidence_sha256'}!=result:
                    raise ValueError('c5 replay result drift')
            checked.append((out,manifest,ledger))
        # All 256 identities validate before any receiver metadata is revised.
        for out,manifest,ledger in checked:
            saved=rev/out.name
            write(saved/'previous-manifest.json',manifest);write(saved/'previous-ledger.json',ledger)
            new=copy.deepcopy(manifest)
            new['runtime']=b.runtime()
            new['intake_revalidation']=dict(previous_manifest_sha256=digest(out/'manifest.json'),
                previous_receiver_runtime=manifest['runtime'],original_execution_metadata='aux-original-manifest.json',
                source_sha256=digest(__file__),new_games=0)
            write(out/'manifest.json',new)
            revised=copy.deepcopy(ledger);revised['manifest_sha256']=digest(out/'manifest.json');write(out/'ledger.json',revised)
            b.load_bound(out);b.inspect(out)
        result=dict(status='PASS_C5_INTAKE_REVALIDATED',shards=4,completed=255,truncated=1,
                    new_games=0,game_evidence_changed=False,previous_receivers_retained=True,
                    runtime=b.runtime(),source_sha256=digest(__file__),observed_at=time.time())
        write(rev/'receipt.json',result);return result

if __name__=='__main__':print(json.dumps(revalidate()))
