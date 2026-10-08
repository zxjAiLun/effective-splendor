"""M72 distribution revision: empirical model snapshots and saved M70 games only."""
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict

from scripts.prism_style_atlas import ROOT, digest, midrank, read

TARGET = 'benchmarks/prism-style-distributions-2026-10-08.json'
WORK = ROOT / 'local-artifacts/prism/style-atlas-20261008/distribution-r2'
MODEL_METRICS = [('low_share', '0–1VP购牌占比', '%'), ('big_printed_vp', '3–5VP印刷分/局', 'VP'),
                 ('noble_coverage', '贵族覆盖', '%'), ('vp_main', 'VP / 本人Main', 'VP/Main')]
GAME_METRICS = [('vp_main', '逐局 VP / 本人Main', 'VP/Main'), ('cards', '逐局购牌数量', '张'),
                ('vp', '逐局终局VP', 'VP'), ('main', '逐局本人Main', 'Main')]


def quantile(values, p):
    ordered = sorted(values)
    if not ordered or not 0 <= p <= 1:
        raise ValueError('invalid quantile input')
    pos = (len(ordered)-1)*p
    lo = math.floor(pos); hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi]-ordered[lo])*(pos-lo)


def histogram(values, bins=24):
    if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError('missing or non-finite observations')
    low, high = min(values), max(values)
    pad=max(abs(low)*.05,.01) if high==low else (high-low)*.07
    low -= pad; high += pad
    counts = [0]*bins
    for v in values:
        counts[min(bins-1, int((v-low)/(high-low)*bins))] += 1
    return dict(min=low, max=high, counts=counts, n=len(values), mean=statistics.fmean(values),
                p10=quantile(values,.1), p25=quantile(values,.25), median=quantile(values,.5),
                p75=quantile(values,.75), p90=quantile(values,.9))


def game_data():
    harvest=ROOT/'local-artifacts/prism/m70-b-continuation/result-review/harvest'
    result=read('benchmarks/m70-prism-b-continuation.result.json')
    groups=[]; ledger=[]; shard_configs={}
    for cohort, actor, label in [('reference','base','M67 B-c20'),('candidate','candidate','M70 c4')]:
        values=defaultdict(list); sums=defaultdict(lambda: defaultdict(int)); grid=set()
        for manifest in sorted((harvest/'evaluation'/cohort/'metrics').glob('*.manifest.json')):
            for entry in json.loads(manifest.read_text('utf-8'))['rows']:
                relative=entry['replay_path'].split('/splendor-m70-b-continuation/',1)[1]
                replay_path=harvest/relative; folder=replay_path.parent
                game=json.loads((folder/'game.json').read_text('utf-8'))
                row=game['row']; seat=row['candidate_seat']; opp=row['opponent']; seed=row['seed']
                assert game['status']=='completed' and row['candidate']==actor
                assert 10010000<=seed<=10010255 and seat in (0,1)
                key=(opp,seed,seat); assert key not in grid; grid.add(key)
                replay=json.loads(replay_path.read_text('utf-8'))
                assert replay['seed']==seed and replay['ruleset_fingerprint']=='1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb'
                assert digest(replay_path)==game['replay_sha256']
                assert digest(folder/'report.json')==game['report_sha256']
                config=json.loads((folder/'match-config.json').read_text('utf-8'))
                canonical=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                assert canonical==game['game_config_sha256'] and config['seed']==seed
                args=config['agents'][seat]['args']; assert args[0]=='agent-prism' and '--sample' not in args and '--sampling' not in args
                shard=folder.parents[3]/'config.json'
                if shard not in shard_configs:shard_configs[shard]=json.loads(shard.read_text('utf-8'))
                shard_config=shard_configs[shard]
                assert shard_config['candidates'][actor]['files'][0]['sha256']==result['candidate_sha256'][actor]
                assert args==shard_config['candidates'][actor]['args']
                assert config['agents'][1-seat]['args']==shard_config['opponents'][opp]['args']
                vp=replay['result']['scores'][seat]; assert vp==row['candidate_points']
                own=[s for s in replay['steps'] if s['actor']==seat]
                main=sum(s['action']['type']!='choose_noble' for s in own)
                cards=sum(s['action']['type'] in ('buy_market','buy_reserved') for s in own)
                assert main>0
                for k,v in [('vp_main',vp/main),('cards',cards),('vp',vp),('main',main)]:values[k].append(v)
                for k,v in [('vp',vp),('main',main),('cards',cards),('games',1)]:sums[opp][k]+=v
                ledger.append(dict(path=str(folder.relative_to(ROOT)).replace('\\','/'),replay_sha256=game['replay_sha256'],
                                   report_sha256=game['report_sha256'],match_config_canonical_sha256=game['game_config_sha256'],match_config_file_sha256=digest(folder/'match-config.json'),game_sha256=digest(folder/'game.json'),shard_config_sha256=digest(shard)))
        opponents=result['acceptance_policy']['common_opponents']
        assert grid=={(o,s,t) for o in opponents for s in range(10010000,10010256) for t in (0,1)}
        for opp,total in sums.items():
            m=next(p['candidate_metrics'] for p in result['pairs'] if p['candidate']==actor and p['opponent']==opp)
            assert total['games']==m['games'] and total['main']==m['total_main_actions']
            assert abs(total['vp']-m['mean_prestige']*m['games'])<1e-7
            assert abs(total['cards']-sum(m['mean_cards_by_vp'].values())*m['games'])<1e-7
        groups.append(dict(model=label,sha256=result['candidate_sha256'][actor],games=len(grid),
                           values=dict(values),pooled_vp_main=sum(t['vp'] for t in sums.values())/sum(t['main'] for t in sums.values()),
                           statistics={k:histogram(v) for k,v in values.items()}))
    WORK.mkdir(parents=True,exist_ok=True)
    ledger_path=WORK/'source-ledger.json';ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return groups,str(ledger_path.relative_to(ROOT)).replace('\\','/'),digest(ledger_path)


def build():
    WORK.mkdir(parents=True,exist_ok=True)
    atlas=read('benchmarks/prism-style-delivery-2026-10-08.json')
    games,ledger,ledger_sha=game_data()
    result=dict(format='prism-empirical-distributions-v1',status='DESCRIPTIVE',
                metrics={'model':[dict(key=k,title=t,unit=u) for k,t,u in MODEL_METRICS],
                         'game':[dict(key=k,title=t,unit=u) for k,t,u in GAME_METRICS]},
                model_groups=[dict(id=g['id'],fixture=g['fixture'],records=[{k:r[k] for k in ['model','sha256','games']+[m[0] for m in MODEL_METRICS]} for r in atlas['records'] if r['group']==g['id']]) for g in atlas['groups']],
                game_models=games,game_scope=dict(round='M70',mode='both-greedy',seed_start=10010000,seed_end=10010255,opponents=['heuristic','general','balance','alpha','beta','released-alpha'],seats=[0,1]),
                source_hashes={p:digest(p) for p in ['benchmarks/prism-style-delivery-2026-10-08.json','benchmarks/m70-prism-b-continuation.result.json','benchmarks/m70-prism-b-continuation.config.json',ledger]},
                source_ledger=ledger,source_ledger_sha256=ledger_sha,
                semantics={'model':'Each observation is one model × cohort aggregate; each model has equal weight. Separate cohorts; no Gaussian fit.',
                           'game':'Each observation is one saved completed candidate game. Histogram reference is selectable B or c4, never independent model samples.',
                           'game_marker':'Arithmetic mean of per-game metric, not pooled VP/Main. Original pooled ratio displayed separately.',
                           'percentile':'Midrank: (lower + 0.5 equal)/N; selected mean in game distribution is NOT a percentile among models.',
                           'quantile':'Linear interpolation on sorted observations at (N-1)*p. Histogram last bin includes maximum.'})
    (ROOT/TARGET).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# M72 分布图修订：模型位置与真实对局分布','',
           '产物：真实经验直方图、均值/分位点/当前位置、原始观测CSV与来源账本。竞技：沿用原结果。风格：描述性筛查；不改变原路线结论或发布状态。',
           '', '模型分布每个模型快照等权；不同cohort分开。M67 A原5个缺项保留。逐局分布只使用M70完整共同池，B/c4各3,072局，不把对局数当模型数。',
           '', '分位位置=(低于当前值数量+0.5×同值数量)/N。分位点使用排序后(N−1)×p线性插值。直方图最后一个区间含最大值；没有拟合正态曲线。', '']
    for g in result['model_groups']:
        lines += [f"## {g['id']} · {len(g['records'])}个模型", '', '| 指标 | 模型 | 当前值 | 本组模型均值 | 位置百分位 | P10 | 中位数 | P90 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for k,t,u in MODEL_METRICS:
            vs=[r[k] for r in g['records']];h=histogram(vs)
            f=lambda v:f'{v*100:.2f}%' if u=='%' else f'{v:.4f}'
            for r in g['records']:lines.append(f"| {t} | {r['model']} | {f(r[k])} | {f(h['mean'])} | {midrank(r[k],vs)*100:.2f}% | {f(h['p10'])} | {f(h['median'])} | {f(h['p90'])} |")
        lines.append('')
    lines += ['## M70逐局分布', '', '| 参照模型 | 指标 | N局 | 逐局均值 | P10 | 中位数 | P90 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in games:
        for k,t,u in GAME_METRICS:
            h=r['statistics'][k];lines.append(f"| {r['model']} | {t} | {h['n']} | {h['mean']:.4f} | {h['p10']:.4f} | {h['median']:.4f} | {h['p90']:.4f} |")
    lines += ['', '逐局均值的VP/Main按每局比率等权；原报告采用ΣVP/Σ本人Main。两者口径不同：', '']
    for r in games:lines.append(f"- {r['model']}：逐局均值 {r['statistics']['vp_main']['mean']:.6f}；原报告合并比率 {r['pooled_vp_main']:.6f}。")
    lines += ['', '## 证据与限制', '', f'分布JSON：`{TARGET}`，SHA `{digest(TARGET)}`。', f'逐局来源账本：`{ledger}`，SHA `{ledger_sha}`。',
              '6,144局逐字节回放/报告SHA、match-config规范化SHA、分片精确权重/实际命令、seed/座位/对手完整网格均核验；逐对手最终VP、本人Main、购牌数与冻结原汇总复算一致。未本地重跑Rust规则或新增对局。',
              '逐局数据保持对手影响；它描述实际比赛表现，不证明主动购牌偏好或奖励机制。M67逐局低VP/时点/投资兑现未从汇总反推。', '']
    (ROOT/'docs/prism/style-distributions-2026-10-08.md').write_text('\n'.join(lines),encoding='utf-8')
    with (ROOT/'outputs/01a11805-prism-style/prism-distribution-observations.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['scope','group','model','observation','metric','value'])
        for g in result['model_groups']:
            for r in g['records']:
                for k,_,_ in MODEL_METRICS:w.writerow(['model',g['id'],r['model'],r['model'],k,r[k]])
        for r in games:
            for k,vs in r['values'].items():
                for i,v in enumerate(vs):w.writerow(['game','M70-common',r['model'],i,k,v])
    receipt=dict(status='PASS',source_ledger_sha256=ledger_sha,completed_games=sum(g['games'] for g in games),
                 unique_models=2,model_cohort_snapshots=sum(len(g['records']) for g in result['model_groups']),
                 raw_identity_grid_and_aggregate_reconciliation='PASS',new_games=0,output_sha256=digest(TARGET))
    (WORK/'data-validation.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':build()
