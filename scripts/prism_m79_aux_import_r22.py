"""SHA-bound intake of the eight resumed auxiliary shards; retain prior intake."""
import argparse,copy,json,time,zipfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_dual_dispatch as dual,prism_m79_import_r2 as imp,prism_bounded_eval as b,prism_m79_evaluate as e
OUT=ROOT/'execution-revisions/aux-finish-r22'

def import_results():
    with lock(OUT/'import-control'):
        if (OUT/'import.json').exists():return read(OUT/'import.json')
        d=read(OUT/'dispatch.json');receipt=read(OUT/'results.receipt.json');archive=OUT/'results.zip'
        if digest(archive)!=receipt['sha256'] or receipt['labels']!=d['labels'] or receipt['resource']['status']!='PASS':
            raise ValueError('completed auxiliary transport binding invalid')
        cpu=receipt['resource']['resources']['cpu_seconds']
        if not 0<=cpu<=d['cpu_reservation']:raise ValueError('auxiliary CPU accounting invalid')
        if receipt['resource']['adapter_sha256']!=read(OUT/'r24-repair.json')['adapter_sha256']:
            raise ValueError('final worker source binding mismatch')
        state=read(ROOT/'pipeline/status.json')
        if state['phase'] not in ('TRAIN','AUDIT','CANDIDATES','CURVE'):raise ValueError('independent stage reached; reconcile before intake')
        stage=OUT/'incoming';stage.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            if set(z.namelist())!=set(receipt['files']):raise ValueError('member set drift')
            for name,info in receipt['files'].items():
                dual.safe_member(name);raw=z.read(name)
                if len(raw)!=info['bytes'] or dual.sha_bytes(raw)!=info['sha256']:raise ValueError('member SHA drift')
                parts=Path(name).parts
                if not (parts[:2]==('execution-revisions','aux-finish-r22') or (parts[0]=='evaluation' and parts[1] in d['labels'])):raise ValueError('unallocated member')
                p=stage/name;p.parent.mkdir(parents=True,exist_ok=True)
                if p.exists() and p.read_bytes()!=raw:raise ValueError('staging collision')
                p.write_bytes(raw)
        keys=read(stage/'execution-revisions/aux-finish-r22/retries.json')
        if set(keys)!=set(d['retry_keys']) or len(keys)!=8:raise ValueError('physical recovery key drift')
        previous={}
        for label in d['labels']:
            p=ROOT/'evaluation'/label
            if digest(p/'ledger.json')!=d['main_ledger_sha256'][label]:raise ValueError('primary cohort changed')
            old=read(p/'ledger.json');new=read(stage/'evaluation'/label/'ledger.json')
            if new['execution_state']!='FINISHED' or len(new['entries'])!=64:raise ValueError('incomplete incoming shard')
            previous[label]={k:v['row'] for k,v in old['entries'].items() if v['state']=='COMPLETED'}
            for key,row in previous[label].items():
                if new['entries'][key].get('row')!=row:raise ValueError('existing terminal result changed')
        canon=imp.replace(dual._canonicalize_imported_shard,[
            ('if semantic_config(config, root) != semantic_config(expected_cfg, root):',"source_root=Path(config['engine']['program']).parent.parent\n    if semantic_config(config, source_root) != semantic_config(expected_cfg, root):"),
            ('validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)',"for name in ('config.json','policy.json','manifest.json','ledger.json'):\n        old=out/name\n        saved=out/('aux-original-'+name)\n        if old.exists() and not saved.exists():saved.write_bytes(old.read_bytes())\n    write_json(config_path,expected_cfg)\n    validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)")])
        # Old primary copies and every original auxiliary byte remain in OUT.
        backup=OUT/'previous-primary-shards';backup.mkdir(exist_ok=True)
        for label in d['labels']:
            dest=ROOT/'evaluation'/label
            dest.rename(backup/label)
            (stage/'evaluation'/label).rename(dest)
            canon(ROOT,label,b,e)
            ledger=read(dest/'ledger.json')
            if any(ledger['entries'][k].get('row')!=v for k,v in previous[label].items()):raise ValueError('canonical terminal drift')
        counts=[b.inspect(ROOT/'evaluation'/label) for label in d['labels']]
        n=sum(x['completed_games'] for x in counts);caps=sum(x['truncated_games'] for x in counts)
        if n+caps!=512:raise ValueError('fixed grid incomplete')
        resource_path=ROOT/'execution-revisions/dual-dispatch-r1/aux-resource.json';resource=read(resource_path)
        if resource['cpu_seconds']!=d['previous_external_cpu']+4240:raise ValueError('shared reservation changed before import')
        write(OUT/'reserved-aux-resource.json',resource)
        resource.update(cpu_seconds=d['previous_external_cpu']+cpu+240,aux_finish_r22_reservation=0,
                        aux_finish_r22_cpu_seconds=cpu,aux_finish_r22_infra_cpu_charge=240,
                        aux_finish_r22_evidence=str(OUT/'import.json'))
        write(resource_path,resource)
        with lock(ROOT/'retry-control'):
            retries=read(ROOT/'infrastructure-retries.json')
            matched=[row for row in retries if row['logical_key'] in d['retry_keys']]
            if len(matched)!=8:raise ValueError('reserved global recovery entries missing')
            for row in matched:
                if row.get('owner')!='aux-finish-r22':raise ValueError('recovery owner drift')
                row.update(state='CONSUMED_EXTERNAL_INFRA_RECOVERY',archive_sha256=digest(archive))
            write(ROOT/'infrastructure-retries.json',retries)
        result=dict(status='PASS_ORIGINAL_440_GAMES_IMPORTED',completed=n,truncated=caps,original_completed=72,
                    new_logical_games=440,prior_terminals_unchanged=72,infra_recoveries=8,
                    measured_cpu_seconds=cpu,conservative_infra_cpu=240,combined_external_cpu=resource['cpu_seconds'],
                    archive_sha256=digest(archive),importer_sha256=digest(__file__),new_games_on_import=0,
                    observed_at=time.time())
        write(OUT/'import.json',result);return result

if __name__=='__main__':print(json.dumps(import_results()))
