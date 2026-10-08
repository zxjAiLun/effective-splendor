"""Register the existing M55 c4 as a named experimental artifact; no new games."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prism_rush_round import frozen, read, write, sha, require
from scripts.prism_rush_report import replace_block, table

NAME='Prism Alpha v0.1.0'
OLD_NAME='Prism Rush v0.1.0'
ART=ROOT/'local-artifacts/prism/alpha-v0.1.0'
RECORD=ROOT/'benchmarks/m55-prism-alpha-v0.1.0.model.json'
REPORT=ROOT/'docs/prism/prism-alpha-v0.1.0-evaluation-summary.md'
HTML=ROOT/'docs/prism/prism-alpha-v0.1.0-comparison.html'
RAW=ROOT/'benchmarks/m55-prism-rush-v0.1.0.result.json'
RAW_SHA='9093d26aa1b8a31fd3874b4b79f046bf098755587a49f0eea345e03649bcac57'
PROFILE=ROOT/'benchmarks/m55-prism-alpha-v0.1.0.style-profile.json'

def card_profile(metrics):
    cards=metrics['mean_cards_by_vp']
    return {**{f'cards_vp_{v}':cards[str(v)] for v in range(6)},
            'cards_3plus':sum(cards[str(v)] for v in (3,4,5)),
            'cards_4plus':sum(cards[str(v)] for v in (4,5)),
            'card_vp_3plus':sum(v*cards[str(v)] for v in (3,4,5)),
            'mean_prestige':metrics['mean_prestige'],
            'vp_per_main_action':metrics['vp_per_main_action']}

def profile_comparison(base,alpha):
    return {key:{'prism_v0.1.1':base[key],'prism_alpha_v0.1.0':alpha[key],
                 'delta':alpha[key]-base[key],
                 'relative_change_percent':(alpha[key]/base[key]-1)*100 if base[key] else None}
            for key in base}

def style_profile(result):
    output={}
    for stage in ('acceptance','development'):
        pairs={(p['candidate'],p['opponent']):p for p in result[stage]['pairs']}
        anchors=[]
        for opponent in ('heuristic-v031','prism-v01'):
            base,alpha=pairs['base',opponent],pairs['rush',opponent]
            anchors.append({'opponent':opponent,'games_per_model':base['candidate_metrics']['games'],
                            'comparison':profile_comparison(card_profile(base['candidate_metrics']),card_profile(alpha['candidate_metrics']))})
        pooled={}
        for model in ('base','rush'):
            selected=[pairs[model,op] for op in ('heuristic-v031','prism-v01')]
            games=sum(p['candidate_metrics']['games'] for p in selected)
            cards={str(v):sum(p['candidate_metrics']['games']*p['candidate_metrics']['mean_cards_by_vp'][str(v)] for p in selected)/games for v in range(6)}
            vp=sum(p['candidate_metrics']['games']*p['candidate_metrics']['mean_prestige'] for p in selected)/games
            # Use summed VP and Main counts, not averages of subgroup ratios.
            total_vp=sum(p['candidate_metrics']['games']*p['candidate_metrics']['mean_prestige'] for p in selected)
            total_main=sum(p['candidate_metrics']['total_main_actions'] for p in selected)
            pooled[model]=card_profile({'mean_cards_by_vp':cards,'mean_prestige':vp,'vp_per_main_action':total_vp/total_main})
        output[stage]={'anchors':anchors,'pooled_games_per_model':games,'pooled_comparison':profile_comparison(pooled['base'],pooled['rush'])}
        if ('rush','base-t1') in pairs:
            direct=pairs['rush','base-t1']
            output[stage]['direct']={'games':direct['candidate_metrics']['games'],
                'orientation':'both players in the same games; candidate is Alpha and opponent is Prism v0.1.1',
                'comparison':profile_comparison(card_profile(direct['opponent_metrics']),card_profile(direct['candidate_metrics']))}
    return {'format':'prism-alpha-descriptive-style-profile-v1','status':'POST_HOC_DESCRIPTIVE_PROFILE',
            'model':'Prism Alpha v0.1.0','source_result':{'path':RAW.relative_to(ROOT).as_posix(),'sha256':RAW_SHA},
            'working_label':'大牌取分 / 偏大牌冲分',
            'definition':'large card means printed 3, 4 or 5 VP; count and printed VP per game, not purchase time or card cost',
            'comparisons':output,'original_gates_and_verdict_unchanged':True,
            'not_a_new_style_acceptance_or_causal_claim':True,'new_games':0,'training_updates':0,
            'next_direction':'PROPOSED: continue existing big-card scoring line with bounded PPO; building branch is deferred'}

def profile_markdown(profile):
    direct=profile['comparisons']['acceptance']['direct']['comparison']
    pooled=profile['comparisons']['acceptance']['pooled_comparison']
    keys=[('局均3 VP卡','cards_vp_3'),('局均4 VP卡','cards_vp_4'),('局均5 VP卡','cards_vp_5'),
          ('局均3～5 VP卡合计','cards_3plus'),('局均3～5 VP卡贡献VP','card_vp_3plus'),('VP / 自身Main','vp_per_main_action')]
    rows=[]
    for label,key in keys:
        d=direct[key]
        rows.append([label,f"{d['prism_v0.1.1']:.4f}",f"**{d['prism_alpha_v0.1.0']:.4f}**",f"**↑ {d['relative_change_percent']:+.2f}%**"])
    return ['## 大牌取分画像（描述性；2026-10-02更正）',
      '**当前更贴切的工作画像是“大牌取分 / 偏大牌冲分”。** 我上一版建议转向基建锚定缺少数据依据；现先沿已观察到的大牌取分倾向继续迭代，基建分支后置。',
      '**下面是Alpha直接对Prism v0.1.1的512局、256双座种子，比较同一场里的双方个人指标。** 大牌在这里明确指卡面3～5 VP；不是所有大牌类别均同幅上涨，也不能仅凭终局数量断定买牌时点。',
      table(['双方个人指标','Prism v0.1.1','Prism Alpha v0.1.0','Alpha相对变化（%不是pp）'],rows),
      f"同一批共同对手的基座/Alpha对照，各模型1,024独立局：3～5VP卡合计 **{pooled['cards_3plus']['prism_v0.1.1']:.4f} → {pooled['cards_3plus']['prism_alpha_v0.1.0']:.4f}，↑{pooled['cards_3plus']['relative_change_percent']:.2f}%**；5VP卡 **{pooled['cards_vp_5']['prism_v0.1.1']:.4f} → {pooled['cards_vp_5']['prism_alpha_v0.1.0']:.4f}，↑{pooled['cards_vp_5']['relative_change_percent']:.2f}%**。前者比直接对战的增幅温和；两个对手上的4/5VP卡均值均提高，3VP卡对Heuristic略降，不能写成全项大幅领先。",
      '开发组每模型/对手128局，3～5VP卡合计对Heuristic由1.9766降至1.9453、对初代由2.1094降至2.0000；大牌数量增长未在这组小样本复现。画像主要依据更大的独立组与直接对战，属于事后描述，不作正式新门或已确认泛化的风格结论。',
      '前16自身Main AUC只衡量早期得分；终局高VP购卡分布衡量整局取分结构，两者可以出现不同幅度。原早期AUC幅度未达目标，不抹掉观察到的大牌取分倾向；购卡总数也不能直接证明“中后期买得更早/结束更快”，购买时点与分段得分曲线尚未在本次新增画像中测量。',
      '画像机读证据：`benchmarks/m55-prism-alpha-v0.1.0.style-profile.json`；原结果、身份和完整双方表保留。']

def main():
    control,config,train=frozen()
    result=read(RAW)
    require(sha(RAW)==RAW_SHA,'original result unchanged')
    source=ROOT/'local-artifacts/prism/rush-v0.1.0/campaign/cycle-4-export/weights.json'
    companion=source.with_name('weights.manifest.json')
    require(sha(source)==result['training']['final_weights_sha256'],'frozen c4 content')
    require(sha(ROOT/config['base_model']['weights_path'])==config['base_model']['sha256'],'frozen base content')

    original_report=ROOT/'docs/prism/prism-rush-v0.1.0-evaluation-summary.md'
    paths=[original_report,ROOT/'docs/m55-prism-rush-style-model.md',ROOT/'docs/m51-prism-model-line.md',ROOT/'docs/aran-model-evolution-matrix.md',ROOT/'handoff.md']
    archive=ART/'identity-2026-10-02'
    ledger=archive/'before-ledger.json'
    if not ledger.exists():
        rows=[]
        for path in paths:
            saved=archive/'before'/path.relative_to(ROOT)
            saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,saved)
            rows.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path),'archive':saved.relative_to(ROOT).as_posix()})
        write(ledger,{'timestamp':datetime.now(timezone.utc).isoformat(),'files':rows,'scope':'neutral experimental identity; no retrospective Rush acceptance'})
    prior=read(ledger)
    for row in prior['files']:require(sha(ROOT/row['archive'])==row['sha256'],'identity pre-change snapshot')
    for src in (source,companion):
        dest=ART/src.name
        if dest.exists():require(sha(dest)==sha(src),'immutable identity copy collision')
        else:
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dest)
        require(sha(dest)==sha(src),'exact identity artifact copy')

    profile=style_profile(result)
    write(PROFILE,profile)
    decision=[
      '# '+NAME+'：固定身份与完整对战记录',
      '**固定实验版本身份：'+NAME+'；与M55最终c4是同一份权重，没有追加训练。** 原开发名为“'+OLD_NAME+' 候选”；Alpha是中性模型线名，不声称冲分或基建风格已经验收。原冲分六门判定 `NOT_ACCEPTED_RUSH_STYLE` 完整保留。',
      table(['身份字段','固定记录'],[
       ['模型名称 / ID',NAME+' / `prism-alpha-v0.1.0`'],
       ['身份登记状态','`REGISTERED_EXPERIMENTAL_MODEL`；可明确引用的实验版本，不是Rush风格已通过'],
       ['谱系','Prism v0.1.1 → M55四轮PPO → M55最终c4 = '+NAME],
       ['固定权重', '`local-artifacts/prism/alpha-v0.1.0/weights.json` / `'+sha(source)+'`'],
       ['训练来源','1,024局、216新更新；原目标为前16自身Main得分曲线（冲分），不是基建专用奖励'],
       ['身份登记','`benchmarks/m55-prism-alpha-v0.1.0.model.json`'],
       ['原验收 / 后续动作','原3PASS/3FAIL保留；此次0新局/更新，未替换默认或部署共享池']]),
      *profile_markdown(profile),
      '## 下一版建议（PROPOSED；未启动）',
      '**优先沿当前大牌取分模型线继续一次有限PPO；基建分支和其他风格后置。** 之前的基建锚定建议作为已更正历史保留于M55迭代日志和登记前快照，不是下一轮当前目标。',
      '从'+NAME+'继承现有policy/value，先补大牌购入时点、卡牌贡献VP与分段得分速度画像，判断下一轮是否继续原冲分奖励或调整其覆盖窗口/效用；目标不是单纯多买大牌，而是更有效地把资源转成得分与胜局。仅奖励买牌数量可能买贵牌却不能取胜。',
      '仍建议一名最终候选、4×256训练；总体棋力保留底线，选择贴合大牌取分的一个主风格目标，其他维度作画像。奖励如改变，style critic应按新效用初始化；若完全相同则按相同合同讨论续训。可接受代价、最低风格幅度、评测预算与新种子均在新采样前冻结。当前没有新训练/比赛进程，`Prism Alpha v0.1.1` 只是后续候选命名建议，尚无权重或结果。',
      table(['方向','判断'],[
       ['当前大牌取分模型线继续PPO','优先：保留已观察到的倾向，改善取分效率和实战表现'],
       ['立即开基建或另一个风格','后置：先把当前方向的画像与验收目标说明白'],
       ['重新从零训练基座','当前无此必要证据；本轮已经完成有效导出和对战闭环']]),
      '## 命名与历史证据',
      '下方旧评测的被测玩家名映射到'+NAME+'，数值/种子/阈值/原判全部沿用原M55证据。文件名中的`rush-v0.1.0`与JSON中的`rush`是冻结实验标识，保留原路径/SHA；它们不是另一份模型或再次训练。可切换彩色页使用当前名称；旧Rush页保留为历史。']
    saved_report=ROOT/next(row['archive'] for row in prior['files'] if row['path']==original_report.relative_to(ROOT).as_posix())
    old_body=saved_report.read_text(encoding='utf-8').split('\n',1)[1]
    body=old_body.replace(OLD_NAME+' 候选',NAME+'（实验版）').replace(OLD_NAME,NAME).replace('prism-rush-v0.1.0-comparison.html','prism-alpha-v0.1.0-comparison.html').replace('prism-rush-v0.1.0-comparison.png','prism-alpha-v0.1.0-comparison.png')
    body=body.replace('本轮候选是已完成、值得保留的实验产物','本轮模型是已登记、值得保留的实验产物')
    document='\n\n'.join(decision)+'\n\n'+body
    REPORT.write_text(document,encoding='utf-8')
    old_title,old_rest=saved_report.read_text(encoding='utf-8').split('\n',1)
    original_report.write_text(old_title+'\n\n> 历史开发名：这份c4现已登记为 **'+NAME+'**，同一权重、同一比赛。当前身份与完整表格见 [版本记录](prism-alpha-v0.1.0-evaluation-summary.md)；本页保留原Rush解读。\n'+old_rest,encoding='utf-8')
    for path,title in [('docs/m55-prism-rush-style-model.md','## M55固定版本：'),('docs/m51-prism-model-line.md','## M55固定实验版本：'),('docs/aran-model-evolution-matrix.md','## M55固定实验版本：')]:
        linked=document.replace('(prism-alpha-v0.1.0-comparison.html)','(prism/prism-alpha-v0.1.0-comparison.html)').replace('(prism-alpha-v0.1.0-comparison.png)','(prism/prism-alpha-v0.1.0-comparison.png)')
        replace_block(ROOT/path,linked.replace('# '+NAME,title+NAME,1))
    template=(ROOT/'scripts/templates/prism-alpha-model-comparison.html').read_text(encoding='utf-8').replace(OLD_NAME+' 候选',NAME+'（实验版）').replace(OLD_NAME,NAME)
    data={'result':result,'config':config,'gates':read(ROOT/'benchmarks/m55-prism-rush-v0.1.0.interpretation.json')['gate_rows'],'sourceSHA':RAW_SHA,'sourcePath':RAW.relative_to(ROOT).as_posix(),'names':{'heuristic-v031':'Heuristic v0.3.1','prism-v01':'初代 Prism v0.1.0','base-t1':'Prism v0.1.1'},'completedLocal':datetime.fromisoformat(result['completed_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}
    data['styleProfile']=profile
    HTML.write_text(template.replace('__MODEL_DATA__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    runtime=json.loads(source.read_text(encoding='utf-8'))
    record={'format':'prism-experimental-model-identity-v1','identity_status':'REGISTERED_EXPERIMENTAL_MODEL','display_name':NAME,'model_id':'prism-alpha-v0.1.0','model_version':'prism-alpha-v0.1.0','weights':{'path':(ART/'weights.json').relative_to(ROOT).as_posix(),'sha256':sha(source),'companion_path':(ART/'weights.manifest.json').relative_to(ROOT).as_posix(),'companion_sha256':sha(companion)},'parent':config['base_model'],'origin':{'milestone':'M55','cycle':4,'run_identity':control['training_run_identity'] if 'training_run_identity' in control else read(companion)['provenance']['run_identity'],'weights_path':source.relative_to(ROOT).as_posix(),'weights_sha256':sha(source)},'runtime':{**{k:v for k,v in runtime.items() if k!='state_dict'},'action_mode':'softmax-t1','temperature':1.0,'no_inference_overlay':True},'historical_names':[OLD_NAME+' 候选','prism-rush-v0.1.0'],'evidence':{'path':RAW.relative_to(ROOT).as_posix(),'sha256':RAW_SHA,'formal_verdict':result['status'],'gates':result['gates'],'independent_games':2560,'development_games':512,'report_path':REPORT.relative_to(ROOT).as_posix(),'report_sha256':sha(REPORT)},'style_status':{'training_objective':'early own-score rush AUC','rush_style':'NOT_ESTABLISHED_AT_PREREGISTERED_TARGET','building_style':'NOT_INDEPENDENTLY_DEFINED_OR_ACCEPTED'},'default_replaced':False,'shared_pool_deployed':False,'git_published':False,'identity_registration_games':0,'identity_registration_training_updates':0,'future_direction':{'status':'PROPOSED','recommendation':'one bounded PPO branch from current policy/value with explicitly defined building anchor before another style','budget_proposal_training_games':1024,'actual_new_games':0,'no_new_model_created':True}}
    record['style_status']['observed_profile']={'label':profile['working_label'],'status':profile['status'],
        'path':PROFILE.relative_to(ROOT).as_posix(),'sha256':sha(PROFILE)}
    record['future_direction']['recommendation']='one bounded PPO continuation of current big-card scoring line; building and other styles deferred'
    record['future_direction']['correction']='earlier building-anchor proposal was not supported by inspected card-profile data; retained in archived decision history'
    write(RECORD,record)
    print('PASS: Prism Alpha v0.1.0 experimental identity registered; same M55 c4; no new games or acceptance changes')

if __name__=='__main__':main()
