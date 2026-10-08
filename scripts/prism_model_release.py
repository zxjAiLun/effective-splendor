"""Publish owner-authorized, exact version identities; never train or run games."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def require(ok,message):
    if not ok:raise ValueError(message)
def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_export(weights,companion,expected):
    require(sha(weights)==expected,'release weight drift')
    w,m=read(weights),read(companion)
    require(w['format']=='prism-weights-v1' and m['format']=='prism-weights-manifest-v1','wrong export format')
    require(w['catalog_fingerprint']==m['catalog_fingerprint'] and m['weights_sha256']==expected,'manifest identity drift')
    require(len(w['state_dict'])==32 and set(w['state_dict'])==set(m['tensors']),'export tensor set drift')
    require(m['tensor_sha256']==canonical(m['tensors']),'tensor manifest drift')
    for key,row in w['state_dict'].items():
        data=np.asarray(row['data'],dtype='<f4')
        require(row['shape']==m['tensors'][key]['shape'] and data.size==int(np.prod(row['shape'])),'tensor shape drift: '+key)
        require(np.isfinite(data).all() and hashlib.sha256(data.tobytes()).hexdigest()==m['tensors'][key]['sha256'],'tensor content drift: '+key)
    return m


def publish(spec_path,root=ROOT):
    root=Path(root);spec=read(spec_path)
    require(spec['authorization']['source']=='human_owner','explicit owner publication required')
    checked=[]
    for item in spec['models']:
        weight=root/item['source_weights'];companion=root/item['source_companion']
        require(sha(companion)==item['source_companion_sha256'],'source companion drift')
        manifest=validate_export(weight,companion,item['weights_sha256'])
        require(manifest['provenance']['cycle']==4,'not the specified final c4')
        result=root/item['original_result'];require(sha(result)==item['original_result_sha256'],'original result drift')
        arm=item['origin']['arm']
        original=read(result);require(original['candidate_sha256'][arm]==item['weights_sha256'],'candidate result identity drift')
        config=root/item['original_config'];require(sha(config)==item['original_config_sha256']==original['config_sha256'],'original config drift')
        require(read(config)['base_model']['sha256']==item['parent']['sha256'],'training parent identity drift')
        audit=root/item['artifact_audit'];require(sha(audit)==item['artifact_audit_sha256'],'artifact audit drift')
        av=read(audit);require(av['status']=='PASS_TRAINING_ARTIFACT_AUDIT','artifact audit not passed')
        ar=av['arms'][arm] if 'arms' in av else av
        require(ar['candidate_sha256']==item['weights_sha256'],'audit candidate identity drift')
        for ref in item['greedy_evidence']:
            p=root/ref['path'];require(sha(p)==ref['sha256'],'greedy evidence drift')
            raw=read(p);require(raw['games']==ref['games'],'greedy game coverage drift')
            config_path=root/ref['config'];plan_path=root/ref['plan'];completion_path=root/ref['completion']
            require(sha(config_path)==raw['config_sha256'] and sha(plan_path)==raw['plan_sha256'],'greedy protocol drift')
            cfg,plan,completion=read(config_path),read(plan_path),read(completion_path)
            require(completion['result_sha256']==sha(p) and completion['games']==raw['games']
                and completion['automatic_game_retries']==0,'greedy completion drift')
            key=ref['candidate_key'];descriptor=cfg['candidates'][key]
            require(plan['candidates'][key]['mode']=='greedy' and descriptor['args'][0]=='agent-prism'
                and descriptor['files'][0]['sha256']==item['weights_sha256'],'release greedy mode/weight drift')
            for pair in raw['pairs']:
                if pair['candidate']!=key:continue
                require(plan['opponents'][pair['opponent']]['mode']=='greedy','opponent not greedy')
                metrics=pair['candidate_metrics']
                require(metrics['games']==len(cfg['seeds'])*2 and metrics['wins']+metrics['ties']+metrics['losses']==metrics['games'],'greedy actor coverage drift')
        dest=root/item['weights_path'];dest_companion=dest.with_name('weights.manifest.json');record=root/item['record_path']
        require(not record.exists(),'model version already registered')
        require(not dest.exists() or sha(dest)==item['weights_sha256'],'version destination collision')
        require(not dest_companion.exists() or sha(dest_companion)==sha(companion),'companion destination collision')
        checked.append((item,weight,companion,dest,dest_companion,original))
    outputs=[]
    # Check every artifact and version destination before the first mutation.
    for item,weight,companion,dest,dest_companion,original in checked:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():shutil.copyfile(weight,dest)
        if not dest_companion.exists():shutil.copyfile(companion,dest_companion)
        require(sha(dest)==item['weights_sha256'] and sha(dest_companion)==sha(companion),'published copy drift')
        record={k:v for k,v in item.items() if k not in ('source_weights','source_companion','record_path')}
        record.update(format='prism-experimental-model-identity-v1',status='RELEASED_EXPERIMENTAL_MODEL',
            identity_status='RELEASED_EXPERIMENTAL_MODEL',released_at=datetime.now(timezone.utc).isoformat(),
            authorization=spec['authorization'],companion_path=dest_companion.relative_to(root).as_posix(),
            companion_sha256=sha(dest_companion),original_research_verdict=original['verdicts'],
            default_replaced=False,pool_deployed=False,studio_deployed=False,git_published=False,
            identity_registration_games=0,identity_registration_training_updates=0,
            release_semantics='Versioned research artifact released by owner practical decision; no universal-strength/default-champion claim. Export provenance remains historical.')
        target=root/item['record_path'];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        outputs.append(dict(path=item['record_path'],sha256=sha(target),display_name=item['display_name']))
    return dict(status='RELEASED_TWO_EXPERIMENTAL_MODELS',models=outputs,new_games=0,new_training=0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True)
    print(json.dumps(publish(p.parse_args().spec),ensure_ascii=False,indent=2))
