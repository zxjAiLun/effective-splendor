"""Owner-selected M67/M70 research versions. Zero games; old publishers stay pinned."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import numpy as np
from scripts.prism_model_release import canonical, read, require, sha, validate_export

ROOT=Path(__file__).resolve().parents[1]


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def derived_manifest(weight,audit):
    w=read(weight);cp=audit['checkpoint'];tensors={}
    require(w['format']=='prism-weights-v1' and len(w['state_dict'])==32,'invalid export')
    for key,row in w['state_dict'].items():
        a=np.asarray(row['data'],dtype='<f4')
        require(np.isfinite(a).all() and a.size==int(np.prod(row['shape'])),'invalid tensor '+key)
        import hashlib
        tensors[key]={'shape':row['shape'],'sha256':hashlib.sha256(a.tobytes()).hexdigest()}
    return dict(format='prism-weights-manifest-v1',weights_sha256=sha(weight),catalog_fingerprint=w['catalog_fingerprint'],
                tensors=tensors,tensor_sha256=canonical(tensors),
                provenance=dict(cycle=cp['cycle'],commit=cp['commit'],run_identity=cp['run_identity'],not_promoted=True,
                                sampling='softmax-t1',derivation='New publication companion derived from immutable export and original training audit; not an original execution manifest'))


def checked_path(root,value,prefix=None):
    p=(root/value).resolve()
    require(p.is_relative_to(root.resolve()),'path outside project')
    if prefix:require(p.is_relative_to((root/prefix).resolve()),'unexpected destination root')
    return p


def preflight(spec,root=ROOT):
    root=Path(root);require(spec['authorization']['source']=='human_owner','owner authorization required')
    require(len({m['model_id'] for m in spec['models']})==len(spec['models']),'duplicate version')
    checked=[];destinations=set()
    for m in spec['models']:
        for p,h in m['source_hashes'].items():require(sha(checked_path(root,p))==h,'source drift '+p)
        weight=checked_path(root,m['source_weights']);companion=checked_path(root,m['source_companion'])
        manifest=validate_export(weight,companion,m['weights_sha256'])
        config=read(root/m['original_config']);result=read(root/m['original_result']);audit=read(root/m['artifact_audit'])
        require(result['source_config_sha256']==sha(root/m['original_config']),'result/config drift')
        require(result['action_mode']=='both-greedy','unexpected result mode')
        require(result['candidate_sha256'][m['result_key']]==m['weights_sha256'],'result candidate drift')
        require(result['candidate_sha256']['base']==config['base_model']['sha256']==m['parent']['sha256'],'parent drift')
        require(sha(root/m['parent']['source_weights'])==m['parent']['sha256'],'parent bytes drift')
        require(audit['status']=='PASS_TRAINING_ARTIFACT_AUDIT' and audit['weights_sha256']==m['weights_sha256'],'artifact audit invalid')
        cp=audit['checkpoint'];require(cp['status']=='PASS' and cp['cycle']==m['origin']['cycle']==manifest['provenance']['cycle'],'final cycle drift')
        require(cp['initialization']['parent_sha256']==m['parent']['sha256'] and cp['exact_export_tensors']==32,'initialization/export drift')
        require(cp['run_identity']==manifest['provenance']['run_identity'] and cp['commit']==manifest['provenance']['commit'],'execution lineage drift')
        require(cp['cycle']==config['training']['arms'][m['origin']['arm']]['cycles'],'not specified final checkpoint')
        if m['origin']['milestone']=='M67':
            entry=result['training_audits'][m['origin']['arm']]
            require(entry['sha256']==sha(root/m['artifact_audit']) and entry['audit']==audit,'M67 saved audit drift')
        else:require(result['training_audit_sha256']==sha(root/m['artifact_audit']),'M70 saved audit drift')
        for e in m['greedy_evidence']:
            raw=read(root/e['result']);cfg=read(root/e['config']);plan=read(root/e['plan']);completion=read(root/e['completion'])
            require(raw['config_sha256'] in [sha(root/e['config']),canonical(cfg)] and raw['plan_sha256']==sha(root/e['plan']),'greedy protocol drift')
            require(completion['result_sha256']==sha(root/e['result']) and completion['games']==raw['games'],'completion drift')
            key=m['result_key'];descriptor=cfg['candidates'][key]
            require(descriptor['args'][0]=='agent-prism' and descriptor['files'][0]['sha256']==m['weights_sha256'],'candidate mode/weight drift')
            require(plan['candidates'][key]['mode']=='greedy' and all(x['mode']=='greedy' for x in plan['opponents'].values()),'not both greedy')
            require(any(p['candidate']==key for p in raw['pairs']),'missing candidate results')
        dest=checked_path(root,m['weights_path'],'local-artifacts/prism');record=checked_path(root,m['record_path'],'benchmarks')
        dc=dest.with_name('weights.manifest.json')
        for p in [dest,dc,record]:require(p not in destinations,'duplicate output path');destinations.add(p)
        require(not record.exists(),'model version already registered')
        require(not dest.exists() or sha(dest)==m['weights_sha256'],'version weight collision')
        require(not dc.exists() or sha(dc)==sha(companion),'version companion collision')
        checked.append((m,weight,companion,dest,dc,record,result))
    return checked


def publish(spec_path,root=ROOT):
    spec=read(spec_path);root=Path(root);checked=preflight(spec,root);outputs=[]
    for m,weight,companion,dest,dc,record,result in checked:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():shutil.copyfile(weight,dest)
        if not dc.exists():shutil.copyfile(companion,dc)
        validate_export(dest,dc,m['weights_sha256'])
        value={k:v for k,v in m.items() if k not in ['record_path','result_key']}
        value.update(format='prism-experimental-model-identity-v1',status='RELEASED_EXPERIMENTAL_MODEL',identity_status='RELEASED_EXPERIMENTAL_MODEL',
            authorization=spec['authorization'],released_at=datetime.now(timezone.utc).isoformat(),companion_path=dc.relative_to(root).as_posix(),
            companion_sha256=sha(dc),original_research_verdict=result['verdicts'],
            default_replaced=False,pool_deployed=False,studio_deployed=False,git_published=False,
            identity_registration_games=0,identity_registration_training_updates=0,
            release_semantics='Owner-selected fixed research version. Balance reference is a designated data baseline, not confirmed balanced style or default champion.')
        write(record,value);outputs.append(dict(path=m['record_path'],sha256=sha(record),display_name=m['display_name'],weights_sha256=sha(dest)))
    receipt=dict(status='RELEASED_THREE_EXPERIMENTAL_MODELS',models=outputs,new_games=0,new_training=0,source_spec_sha256=sha(spec_path))
    write(root/spec['receipt_path'],receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--check-only',action='store_true');a=p.parse_args()
    print(json.dumps(dict(status='PASS_PREFLIGHT',models=len(preflight(read(a.spec)))) if a.check_only else publish(a.spec),ensure_ascii=False))
