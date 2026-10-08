"""Existing-data style atlas and explicit retrospective band classifier; zero games."""
import csv, hashlib, json, math, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()

def aggregate(metrics):
    n=sum(m['games'] for m in metrics)
    if not n:raise ValueError('empty sample')
    cards=[sum(m['mean_cards_by_vp'][str(i)]*m['games'] for m in metrics)/n for i in range(6)]
    total=sum(cards)
    if not total:raise ValueError('no purchases')
    nobles=sum(m['games_with_nobles'] for m in metrics)
    vp=sum(m['mean_prestige']*m['games'] for m in metrics)
    main=sum(m['total_main_actions'] for m in metrics)
    return dict(games=n,cards_by_vp=cards,low_cards=cards[0]+cards[1],low_share=(cards[0]+cards[1])/total,
                big_printed_vp=sum(i*cards[i] for i in [3,4,5]),big_share=sum(cards[3:])/total,
                cards_4plus=cards[4]+cards[5],noble_games=nobles,noble_coverage=nobles/n,
                total_vp=vp,total_main=main,vp_main=vp/main if main else None,
                first_big_main=None,first_big_coverage=None,early_low_cards=None,early_discount_redemptions=None)

def midrank(value,roster):
    if not roster:raise ValueError('empty calibration roster')
    return (sum(v<value for v in roster)+.5*sum(v==value for v in roster))/len(roster)

def grid_digest(grid):
    """Model-independent observed (exact opponent identity, seed, actor seat)."""
    normalized=sorted((r['opponent'],r['seed'],r['seat']) for r in grid)
    return hashlib.sha256(json.dumps(normalized,separators=(',',':')).encode()).hexdigest()

def valid_observed_grid(profile):
    try:
        start,end=profile['seed_start'],profile['seed_end'];fixture=profile['opponent_fixture'];grid=profile['observed_grid']
        if type(start) is not int or type(end) is not int or end<start:return False
        if not fixture or len(set(fixture))!=len(fixture):return False
        if any(not isinstance(op,str) or re.fullmatch(r'[0-9a-f]{64}',op) is None for op in fixture):return False
        expected=len(fixture)*(end-start+1)*2
        if profile['games']!=expected or len(grid)!=expected:return False
        keys=[]
        for row in grid:
            if row['opponent'] not in fixture or type(row['seed']) is not int or not start<=row['seed']<=end or type(row['seat']) is not int or row['seat'] not in [0,1]:return False
            keys.append((row['opponent'],row['seed'],row['seat']))
        return len(set(keys))==expected and grid_digest(grid)==profile['observed_grid_sha256']
    except (KeyError,TypeError,ValueError):return False

def classify(d,policy,matched=False):
    if not matched:return {'route':'undetermined','level':'INSUFFICIENT','reason':'No exact matched Balance reference'}
    required={
        'Alpha':['big_printed_vp','low_share','first_big_main','first_big_coverage'],
        'Beta':['low_share','low_cards','early_low_cards','early_discount_redemptions'],
        'Balance':['low_share','big_printed_vp','early_low_cards','first_big_main','first_big_coverage','noble_coverage'],
    }
    missing_by_route={route:[k for k in keys if type(d.get(k)) not in (int,float) or not math.isfinite(d[k])] for route,keys in required.items()}
    eligible=lambda route:not missing_by_route[route]
    a=policy['alpha'];b=policy['beta'];q=policy['balance']
    hits=[]
    if eligible('Alpha') and d['big_printed_vp']>=a['big_printed_vp_delta_min'] and d['low_share']<=a['low_vp_share_delta_max'] and d['first_big_main']<=a['first_big_main_delta_max'] and d['first_big_coverage']>=a['first_big_coverage_delta_min']:hits.append('Alpha')
    if eligible('Beta') and d['low_share']>=b['low_vp_share_delta_min'] and d['low_cards']>=b['low_vp_cards_delta_min'] and d['early_low_cards']>=b['early_low_vp_cards_delta_min'] and d['early_discount_redemptions']>=b['early_discount_redemptions_delta_min']:hits.append('Beta')
    limits={'low_share':q['low_vp_share_delta_abs_max'],'big_printed_vp':q['big_printed_vp_delta_abs_max'],'early_low_cards':q['early_low_vp_cards_delta_abs_max'],'first_big_main':q['first_big_main_delta_abs_max'],'first_big_coverage':q['first_big_coverage_delta_abs_max'],'noble_coverage':q['noble_coverage_delta_abs_max']}
    if eligible('Balance') and all(abs(d[k])<=v for k,v in limits.items()):hits.append('Balance')
    incomplete=any(missing_by_route.values())
    return {'route':'undetermined' if incomplete else hits[0] if len(hits)==1 else 'mixed' if hits else 'undetermined',
            'level':'DESCRIPTIVE' if hits and not incomplete else 'INSUFFICIENT','hits':hits,
            'provisional_hits':hits if incomplete else [],'missing_by_route':missing_by_route,
            'missing':sorted({k for keys in missing_by_route.values() for k in keys}),
            'policy_status':policy['status']}

def classify_profiles(candidate,reference,policy):
    """Public entry point: identity/cohort validation precedes numerical bands."""
    balance_sha=policy['reference_sha256']
    required=['mode','opponent_fixture','seed_start','seed_end','seats','rules_sha256','observed_grid_sha256','metrics_semantics']
    valid_hash=lambda x:isinstance(x,str) and re.fullmatch(r'[0-9a-f]{64}',x) is not None
    valid_identity=all(valid_hash(p.get(k)) for p in [candidate,reference] for k in ['sha256','rules_sha256','observed_grid_sha256'])
    valid_grid=all(p.get('missing_games')==0 and p.get('games',0)>0 and p.get('seats')==[0,1] and p.get('mode')=='both-greedy' and p.get('metrics_semantics')==policy['metrics_semantics_id'] and valid_observed_grid(p) for p in [candidate,reference])
    if not valid_identity or not valid_grid or reference.get('sha256')!=balance_sha or any(k not in candidate or k not in reference or candidate[k]!=reference[k] for k in required) or candidate.get('games')!=reference.get('games'):
        return classify({},policy,False)
    deltas={k:(candidate.get(k)-reference.get(k) if candidate.get(k) is not None and reference.get(k) is not None else None) for k in ['big_printed_vp','low_share','low_cards','first_big_main','first_big_coverage','early_low_cards','early_discount_redemptions','noble_coverage']}
    return classify(deltas,policy,True)

def build():
    catalog=read('benchmarks/prism-model-catalog-2026-10-05.json')
    known={m['display_name']:m['weights_sha256'] for m in catalog['models']}
    names={'alpha':'Prism Alpha v0.1.4','balance':'Prism Balance v0.1.0','beta':'Prism Beta v0.1.0',
           'general':'Prism v0.1.1','initial':'Prism v0.1.0','released-alpha':'Prism Alpha v0.1.5','heuristic':'Heuristic v0.3.1'}
    sources=[('M67','benchmarks/m67-prism-alpha-repeat.result.json'),('M66','benchmarks/m66-prism-alpha-dsw.result.json'),('M70','benchmarks/m70-prism-b-continuation.result.json')]
    records=[];source_hashes={};groups=[]
    for round_id,path in sources:
        result=read(path);source_hashes[path]=digest(path)
        assert result['action_mode']=='both-greedy'
        if round_id=='M67':models={'base':'Prism Alpha v0.1.5','candidate-a':'M67 A-c20','candidate-b':'M67 B-c20'}
        elif round_id=='M66':models={'base':'Prism Alpha v0.1.5','candidate':'M66 c4'}
        else:models={'base':'M67 B-c20','candidate':'M70 c4'}
        pool=sorted(set(p['opponent'] for p in result['pairs'] if p['candidate']=='base'))
        pairs=[p for p in result['pairs'] if p['candidate'] in models and p['opponent'] in pool]
        assert len(pairs)==len(models)*len(pool)
        for kind in ['main','anchors']:
            group=f'{round_id}-{kind}';group_records=[]
            actor_keys=models if kind=='main' else {k:names[k] for k in pool}
            for key,label in actor_keys.items():
                selected=[p for p in pairs if p['candidate']==key] if kind=='main' else [p for p in pairs if p['opponent']==key]
                metric_key='candidate_metrics' if kind=='main' else 'opponent_metrics'
                metrics=[p[metric_key] for p in selected]
                identity=result['candidate_sha256'].get(key) if kind=='main' else known.get(label)
                row={'group':group,'round':round_id,'kind':kind,'model':label,'sha256':identity or 'non-neural heuristic',
                     'mode':'both-greedy','opponent_fixture':list(models.values()) if kind=='anchors' else [names[k] for k in pool],
                     'source':path,'source_sha256':source_hashes[path],'source_pairs':[{'candidate':p['candidate'],'opponent':p['opponent'],'games':p[metric_key]['games']} for p in selected],
                     'match_note':'M67 has five known missing games; aggregates are near-matched, not exact paired style CIs' if round_id=='M67' else 'Same fixture and seed schedule within group',
                     **aggregate(metrics)}
                if identity is None and kind=='main':row['sha256']=known.get(label,'UNKNOWN')
                row['classification']=classify({},read('benchmarks/prism-style-bands-v1.policy.json'),False)
                group_records.append(row)
            for row in group_records:
                row['within_group_percentiles']={m:midrank(row[m],[x[m] for x in group_records]) for m in ['low_share','big_printed_vp','noble_coverage','vp_main']}
            records.extend(group_records)
            groups.append({'id':group,'models':len(group_records),'fixture':group_records[0]['opponent_fixture']})
    policy=read('benchmarks/prism-style-bands-v1.policy.json')
    output={'format':'prism-style-atlas-v1','task_kind':'existing-data report + offline classifier implementation',
            'scope':'Six currently registered neural models, Heuristic, M66/M67/M70 candidates; older unpublished branches not exhaustively included',
            'status':'DESCRIPTIVE_SCREENING_NOT_RELEASE','source_hashes':source_hashes,'policy_sha256':digest('benchmarks/prism-style-bands-v1.policy.json'),
            'notes':['0–5VP is printed prestige, not gem cost; actual Splendor tiers are 1–3','Separate round/fixture/mode; do not pool different groups','Percentiles rank model snapshots, not games or a known population','A has 5 missing games; rank descriptively without inventing draws','No matched Balance/temporal-investment measurements for the current three candidates: formal automatic route stays undetermined'],
            'groups':groups,'records':records}
    target=ROOT/'benchmarks/prism-style-atlas-2026-10-08.json';target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    out=ROOT/'outputs/01a11805-prism-style';out.mkdir(parents=True,exist_ok=True)
    cols=['group','model','games','sha256','low_cards','low_share','big_printed_vp','big_share','cards_4plus','noble_coverage','vp_main']
    with (out/'prism-style-atlas.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader();writer.writerows({k:r[k] for k in cols} for r in records)
    return output

if __name__=='__main__':
    result=build();print(json.dumps({'groups':len(result['groups']),'model_cohort_rows':len(result['records']),'sources':result['source_hashes']},ensure_ascii=False))
