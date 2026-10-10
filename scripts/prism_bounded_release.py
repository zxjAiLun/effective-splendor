"""Register exact bounded-run research versions and revise display identities only."""
import argparse
import copy
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import shutil

from scripts.prism_generation_release import derived_manifest, checked_path, write
from scripts.prism_model_release import read, require, sha, validate_export

ROOT = Path(__file__).resolve().parents[1]


def preflight(spec, root=ROOT):
    require(spec['authorization']['source'] == 'human_owner', 'owner authorization required')
    require(len({m['model_id'] for m in spec['models']}) == len(spec['models']), 'duplicate version')
    registry = read(root/spec['registry'])
    require(sha(root/spec['registry']) == spec['registry_sha256'], 'existing registry drift')
    existing = {m['model_id'] for m in registry['models']}
    outputs = set()
    checked = []
    for m in spec['models']:
        require(m['model_id'] not in existing, 'version already registered')
        for p, digest in m['source_hashes'].items():
            require(sha(checked_path(root, p)) == digest, 'source drift: '+p)
        weight = checked_path(root, m['source_weights'])
        require(sha(weight) == m['weights_sha256'], 'weight identity drift')
        raw, cfg, audit, candidates = [read(root/m[k]) for k in ['original_result','original_config','artifact_audit','candidate_registry']]
        key = m['origin']['arm']; cp = audit['checkpoint']
        require(raw['action_mode'] == 'both-greedy', 'unexpected evaluation mode')
        require(raw['source_config_sha256'] == sha(root/m['original_config']), 'result/config drift')
        require(raw['candidate_registry_sha256'] == sha(root/m['candidate_registry']), 'candidate registry drift')
        require(raw['candidate_sha256'][key] == candidates['models'][key]['sha256'] == m['weights_sha256'], 'candidate drift')
        require(candidates['models'][key]['audit_sha256'] == sha(root/m['artifact_audit']), 'audit binding drift')
        require(audit['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT' and audit['weights_sha256'] == m['weights_sha256'], 'artifact audit invalid')
        require(cp['status'] == 'PASS' and cp['exact_export_tensors'] == 32, 'checkpoint audit invalid')
        require(cp['cycle'] == m['origin']['cycle'] == cfg['training']['arms'][key]['cycles'], 'not final checkpoint')
        require(cp['initialization']['parent_sha256'] == cfg['base_model']['sha256'] == raw['candidate_sha256']['base'] == m['parent']['sha256'], 'parent drift')
        require(sha(root/m['parent']['source_weights']) == m['parent']['sha256'], 'parent bytes drift')
        require(audit['parity']['status'] == 'PASS', 'parity not passed')
        for pair in raw['pairs']:
            if pair['candidate'] != key: continue
            require(pair['candidate_mode'] == pair['opponent_mode'] == 'greedy', 'pair mode drift')
            for side in ['candidate_metrics','opponent_metrics']:
                stats = pair[side]
                require(stats['games'] == sum(stats[k] for k in ['wins','ties','losses']), 'WDL count drift')
        require(any(p['candidate'] == key for p in raw['pairs']), 'missing competitive evidence')
        manifest = derived_manifest(weight, audit)
        paths = [checked_path(root, m['weights_path'], 'local-artifacts/prism'), checked_path(root, m['record_path'], 'benchmarks')]
        paths.append(paths[0].with_name('weights.manifest.json'))
        for p in paths:
            require(p not in outputs and not p.exists(), 'output collision: '+str(p))
            outputs.add(p)
        checked.append((m, raw, manifest))
    return checked


def publish(spec_path, root=ROOT):
    spec_path = Path(spec_path).resolve()
    spec = read(spec_path); checked = preflight(spec, root); registry = read(root/spec['registry']); outputs=[]
    for m, raw, manifest in checked:
        dest = root/m['weights_path']; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/m['source_weights'], dest)
        companion = dest.with_name('weights.manifest.json'); write(companion, manifest)
        validate_export(dest, companion, m['weights_sha256'])
        record = copy.deepcopy(m)
        record.update(format='prism-experimental-model-identity-v1', status='RELEASED_EXPERIMENTAL_MODEL', identity_status='RELEASED_EXPERIMENTAL_MODEL', authorization=spec['authorization'], released_at=datetime.now(timezone.utc).isoformat(), companion_path=companion.relative_to(root).as_posix(), companion_sha256=sha(companion), companion_derivation=manifest['provenance']['derivation'], original_result_sha256=sha(root/m['original_result']), original_research_verdict={'statistics':raw['per_training_seed'][m['origin']['arm']], 'grid_status':raw['grid_status'], 'published':raw['published']}, default_replaced=False, pool_deployed=False, studio_deployed=False, git_published=False, identity_registration_games=0, identity_registration_training_updates=0)
        write(root/m['record_path'], record)
        entry={k:record[k] for k in ['model_id','display_name','original_checkpoint','weights_sha256','parent','designated_data_baseline']}
        entry.update(record_path=m['record_path'], record_sha256=sha(root/m['record_path']))
        registry['models'].append(entry); outputs.append(entry)
    registry.setdefault('authorization_history', []).append(spec['authorization'])
    registry['latest_registration']={'spec':spec_path.relative_to(root).as_posix(),'sha256':sha(spec_path),'date':'2026-10-10'}
    write(root/spec['registry'], registry)
    receipt={'status':'RELEASED_EXPERIMENTAL_MODELS','models':outputs,'source_spec_sha256':sha(spec_path),'registry_sha256':sha(root/spec['registry']),'new_games':0,'new_training_updates':0}
    write(root/spec['receipt_path'], receipt)
    return receipt


def build_reading(spec_path, root, templates):
    from scripts.prism_human_report import write_markdown
    spec = read(spec_path)
    for k in ['source_html','source_markdown','result']:
        require(sha(root/spec[k]) == spec[k+'_sha256'], 'reading input drift: '+k)
    document=(root/spec['source_html']).read_text(encoding='utf-8')
    pattern=r'(<script id="report-data" type="application/json">)(.*?)(</script>)'
    match=re.search(pattern,document,re.S); require(match is not None,'missing source reading data')
    payload=json.loads(match[2]); original=copy.deepcopy(payload); raw=read(root/spec['result'])
    require(payload['result']['all']['pairs'] == raw['pairs'], 'reading pairs differ from frozen result')
    for key, ref in spec['model_releases'].items():
        require(sha(root/ref['record']) == ref['sha256'], 'release record drift')
        release=read(root/ref['record'])
        require(release['status']=='RELEASED_EXPERIMENTAL_MODEL', 'unregistered identity')
        require(release['weights_sha256']==raw['candidate_sha256'][ref['weight_binding_key']], 'display weight drift')
        validate_export(root/release['weights_path'],root/release['companion_path'],release['weights_sha256'])
        payload['names'][key]=release['display_name']
    payload['story'].update(spec['story_updates'])
    require(payload['result']==original['result'],'numeric evidence mutation')
    out=root/spec['output']; require(not out.exists(),'preserve previous reading revision')
    payload['links'].update(main=out.name,audit=out.with_suffix('.audit.html').name,markdown=out.with_suffix('.reading.md').name)
    payload['links']['related'].append({'href':Path(spec['source_html']).name,'label':'登记前阅读快照'})
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    document=document[:match.start(2)]+encoded+document[match.end(2):]
    old="'本页只展示双方 greedy 的比赛。对比版本默认是训练父代；候选是同一份最终权重，尚未发布新版本。'"
    require(document.count(old)==1,'publication note template changed')
    document=document.replace(old,'E(S.publication_note)')
    document=document.replace('<title>'+html.escape(original['story']['title'])+'</title>','<title>'+html.escape(payload['story']['title'])+'</title>')
    out.write_text(document,encoding='utf-8'); write_markdown(out.with_suffix('.reading.md'),payload)
    if '## 冻结主要统计' in (root/spec['source_markdown']).read_text(encoding='utf-8'):
        tail=(root/spec['source_markdown']).read_text(encoding='utf-8').split('## 冻结主要统计',1)[1]
        with out.with_suffix('.reading.md').open('a',encoding='utf-8') as f:f.write('\n\n## 冻结主要统计'+tail)
    shutil.copyfile(root/spec['source_audit'],out.with_suffix('.audit.html'))
    receipt={'format':'prism-registered-reading-receipt-v1','spec_sha256':sha(spec_path),'adapter_sha256':sha(Path(__file__)),'html_sha256':sha(out),'reading_markdown_sha256':sha(out.with_suffix('.reading.md')),'result_sha256':sha(root/spec['result']),'numeric_payload_unchanged':True,'new_games':0,'pixel_visual':'NOT_VERIFIED'}
    write(out.with_suffix('.reading-receipt.json'),receipt); return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--spec',type=Path,required=True); parser.add_argument('--check-only',action='store_true'); args=parser.parse_args()
    print(json.dumps({'status':'PASS_PREFLIGHT','models':len(preflight(read(args.spec)))} if args.check_only else publish(args.spec),ensure_ascii=False))
