"""Offline candidate identity, saved-replay profiles and disposition. Never dispatch games."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
from decimal import Decimal, ROUND_HALF_UP

ROOT = Path(__file__).resolve().parents[1]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def bound(root, item):
    path = (root / item['path']).resolve()
    require(digest(path) == item['sha256'], 'input SHA drift: ' + item['path'])
    return path


def expected_grid(contract):
    """Per-opponent ranges, not one fictitious Cartesian seed range."""
    ev = contract['evaluation']
    result = set()
    for opponent, limits in {**ev['common_seed_by_opponent'], **ev['coverage_seed_by_opponent']}.items():
        start, end = limits
        require(type(start) is int and type(end) is int and end >= start, 'invalid seed range')
        for model in ('a', 'base'):
            result.update((model, opponent, seed, seat) for seed in range(start, end + 1) for seat in (0, 1))
    result.update(('a', 'parent', seed, seat) for seed in
                  range(ev['direct_seed_start'], ev['direct_seed_end'] + 1) for seat in (0, 1))
    return result


def observed_grid(rows, model, opponents):
    keys = [(r['opponent_identity'], r['seed'], r['seat']) for r in rows
            if r['model'] == model and r['opponent'] in opponents]
    require(len(keys) == len(set(keys)), 'duplicate observed identity/seed/seat')
    return {'entries': [dict(opponent=o, seed=s, seat=t) for o, s, t in sorted(keys)],
            'sha256': canonical(sorted(keys)), 'games': len(keys)}


def classify_matched_profiles(candidate, reference, policy):
    """v2 adapter accepts audited per-opponent seed grids; retains fixed anchor."""
    from scripts.prism_style_atlas import classify
    fields = ('rules_sha256', 'mode', 'metrics_semantics')
    reason = None
    if reference['sha256'] != policy['reference_sha256']:
        reason = 'FIXED_STYLE_ANCHOR_HAS_NO_MATCHED_MEASURED_PROFILE'
    elif candidate.get('mode') != 'both-greedy' or any(candidate.get(k) != reference.get(k) for k in fields):
        reason = 'MODE_RULES_OR_METRICS_MISMATCH'
    elif candidate.get('metrics_semantics') != policy['metrics_semantics_id']:
        reason = 'METRIC_POLICY_SEMANTICS_MISMATCH'
    else:
        for profile in (candidate, reference):
            grid = profile['grid']
            entries = [(r['opponent'], r['seed'], r['seat']) for r in grid['entries']]
            expected = {(o, s, t) for o, limits in profile['seed_by_opponent'].items()
                        for s in range(limits[0], limits[1] + 1) for t in (0, 1)}
            if (len(entries) != len(set(entries)) or set(entries) != expected
                    or grid['sha256'] != canonical(sorted(entries)) or grid['games'] != len(expected)):
                reason = 'INCOMPLETE_OR_DRIFTED_OBSERVED_GRID'
        if candidate['grid'] != reference['grid']:
            reason = 'UNMATCHED_OBSERVED_GRID'
    if reason:
        return dict(route='undetermined', evidence_level='INSUFFICIENT', reason=reason,
                    fixed_anchor_sha256=policy['reference_sha256'])
    keys = ('big_printed_vp', 'low_share', 'low_cards', 'first_big_main', 'first_big_coverage',
            'early_low_cards', 'early_discount_redemptions', 'noble_coverage')
    delta = {k: candidate['metrics'][k] - reference['metrics'][k]
             if candidate['metrics'].get(k) is not None and reference['metrics'].get(k) is not None
             else None for k in keys}
    result = classify(delta, policy, True)
    result['evidence_level'] = result.pop('level')
    result['fixed_anchor_sha256'] = policy['reference_sha256']
    return result


def load_evaluation(root, rawroot, contract, result, manifest):
    """Verify stored bytes, frozen grids/modes/weights, terminal rows and WDL."""
    expected = expected_grid(contract)
    plan = read(rawroot / 'evaluation-plan.json')
    require(plan['config_sha256'] == result['source_config_sha256'], 'plan contract mismatch')
    require(plan['candidate_registry_sha256'] == result['candidate_registry_sha256'], 'plan candidate mismatch')
    require(digest(rawroot / 'candidate-registry.json') == result['candidate_registry_sha256'], 'registry mismatch')
    for rel, item in manifest['members'].items():
        path = (rawroot / rel).resolve()
        require(path.is_relative_to(rawroot.resolve()), 'unsafe evidence path')
        require(path.stat().st_size == item['bytes'] and digest(path) == item['sha256'], 'saved evidence drift: ' + rel)
    seen, rows, failures = set(), [], []
    engine_id = None
    for shard in plan['shards']:
        directory = rawroot / 'evaluation' / shard['label']
        require(digest(directory / 'manifest.json') == shard['manifest_sha256'], 'shard manifest drift')
        config, ledger, sm = (read(directory / x) for x in ('config.json', 'ledger.json', 'manifest.json'))
        require(canonical(config) == sm['config_sha256'], 'shard config drift')
        require(canonical(read(directory / 'policy.json')) == sm['policy_sha256'], 'shard policy drift')
        if engine_id is None:
            engine_id = config['engine']['sha256']
        require(config['engine']['sha256'] == engine_id, 'mixed rule engines')
        jobs = {(m, o, s, t) for m in config['candidates'] for o in config['opponents']
                for s in config['seeds'] for t in (0, 1)}
        require(jobs <= expected and not jobs & seen, 'extra or duplicate shard grid')
        require(len(ledger['entries']) == len(jobs), 'shard ledger count mismatch')
        for model, opponent, seed, seat in sorted(jobs):
            key = f'{model}/{opponent}/seed-{seed}/seat-{seat}'
            entry = ledger['entries'][key]
            seen.add((model, opponent, seed, seat))
            descriptors = [config['candidates'][model], config['opponents'][opponent]]
            identity = []
            for index, desc in enumerate(descriptors):
                command = desc['args'][0]
                require(command in ('agent-prism', 'agent-heuristic-v02'), 'saved mode is not greedy')
                weights = desc.get('files', [])
                sha = weights[0]['sha256'] if weights else desc['sha256']
                wanted = result['candidate_sha256'][model] if index == 0 else (
                    contract['assets'][opponent]['sha256'] if opponent != 'heuristic' else desc['sha256'])
                require(sha == wanted, 'saved actor/opponent weight drift')
                identity.append(sha)
            game = directory / 'games' / model / opponent / f'seed-{seed}-seat-{seat}'
            if entry['state'] != 'COMPLETED':
                require(entry['state'] == 'RETAINED_FAILURE', 'unfinished ledger entry')
                failures.append(dict(model=model, opponent=opponent, seed=seed, seat=seat,
                                     state=entry['state'], kind=entry.get('kind'), source=str(game.relative_to(rawroot))))
                continue
            for name in ('replay.json', 'report.json', 'game.json', 'match-config.json'):
                require(digest(game / name) == entry['evidence_sha256'][name], 'ledger evidence drift')
            saved_match = read(game / 'match-config.json')
            ordered = descriptors if seat == 0 else descriptors[::-1]
            require(saved_match['seed'] == seed and all(a['program'] == d['program'] and a['args'] == d['args']
                    for a, d in zip(saved_match['agents'], ordered)) and len(saved_match['agents']) == 2,
                    'actual match commands drift')
            replay, report = read(game / 'replay.json'), read(game / 'report.json')
            require(replay['seed'] == seed and report['outcome']['status'] == 'completed', 'terminal/seed mismatch')
            require(replay['result'] == report['outcome']['result'], 'report/replay result mismatch')
            row = entry['row']
            require((row['candidate'], row['opponent'], row['seed'], row['candidate_seat']) ==
                    (model, opponent, seed, seat), 'ledger row identity mismatch')
            ranks = replay['result']['ranks']
            score = .5 if ranks[seat] == ranks[1-seat] else float(ranks[seat] < ranks[1-seat])
            require(score == row['candidate_score'], 'ledger/replay score mismatch')
            rows.append(dict(model=model, opponent=opponent, seed=seed, seat=seat, score=score,
                             opponent_identity=identity[1], replay_path=game / 'replay.json'))
    require(seen == expected, 'incomplete overall planned grid')
    require(len(rows) == result['games'] and len(seen) == result['planned_games'], 'result total mismatch')
    require(len(failures) == result['planned_games'] - result['games'], 'missing result count mismatch')
    for pair in result['pairs']:
        scores = Counter(r['score'] for r in rows if r['model'] == pair['candidate'] and r['opponent'] == pair['opponent'])
        m = pair['candidate_metrics']
        require((scores[1], scores[.5], scores[0]) == (m['wins'], m['ties'], m['losses']), 'raw/result WDL mismatch')
        for seat_row in pair['seats']:
            subset = Counter(r['score'] for r in rows if r['model'] == pair['candidate']
                             and r['opponent'] == pair['opponent'] and r['seat'] == seat_row['candidate_seat'])
            m = seat_row['candidate']
            require((subset[1], subset[.5], subset[0]) == (m['wins'], m['ties'], m['losses']), 'seat WDL mismatch')
    return rows, failures, engine_id


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_profile_totals(profiles, metrics):
    require(len(profiles) == metrics['games'], 'projected game count mismatch')
    require(sum(p['main_actions'] for p in profiles) == metrics['total_main_actions'], 'projected Main totals mismatch')
    cards = Counter(e['printed_vp'] for p in profiles for e in p['first_big_purchase_events'])
    for vp in range(6):
        require(abs(cards[vp] - metrics['mean_cards_by_vp'][str(vp)] * metrics['games']) < 1e-7,
                'projected purchased-card totals mismatch')


def build(spec_path, root=ROOT):
    spec_path, root = Path(spec_path), Path(root)
    spec = read(spec_path)
    require(spec['format'] == 'prism-candidate-archive-spec-v1', 'unsupported archive spec')
    sources = {key: bound(root, value) for key, value in spec['inputs'].items()}
    result, contract, registry, audit, policy = (read(sources[k]) for k in
                                               ('result', 'contract', 'registry', 'audit', 'style_policy'))
    candidate = spec['candidate']
    require(digest(sources['weights']) == candidate['sha256'] == result['candidate_sha256']['a']
            == registry['models']['a']['sha256'] == audit['checkpoint']['weights_sha256'], 'candidate identity mismatch')
    require(registry['parent_sha256'] == contract['base_model']['sha256'] == result['candidate_sha256']['base'], 'parent mismatch')
    require(digest(sources['contract']) == result['source_config_sha256'] and
            result['acceptance_policy'] == contract['evaluation'], 'frozen contract drift')
    require(digest(sources['registry']) == result['candidate_registry_sha256'] and
            digest(sources['audit']) == registry['models']['a']['audit_sha256'], 'audit binding mismatch')
    require(audit['checkpoint']['status'] == 'PASS' and audit['checkpoint']['cycle'] == candidate['cycle'], 'invalid final checkpoint')
    rawroot = sources['replay_manifest'].parent
    rows, failures, rules = load_evaluation(root, rawroot, contract, result, read(sources['replay_manifest']))
    from scripts.prism_replay_profile import profile_saved_replays, aggregate_profiles
    print('Stored identity/grid/WDL checks PASS; projecting saved replays (0 new games)', flush=True)
    profile_rows = [dict(game_key=f"{r['model']}/{r['opponent']}/seed-{r['seed']}/seat-{r['seat']}",
                         replay_path=r['replay_path'], replay_sha256=digest(r['replay_path']),
                         candidate_model=r['model'], opponent_model=r['opponent'], candidate_seat=r['seat'],
                         seed=r['seed'], candidate_sha256=result['candidate_sha256'][r['model']],
                         opponent_sha256=r['opponent_identity'], opponent=r['opponent']) for r in rows]
    extracted = profile_saved_replays(profile_rows)
    write_json(rawroot.parent/'replay-profile-verification.json', extracted['verify_receipt'])
    grouped, seat_groups, opposite_groups = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        key = f"{row['model']}/{row['opponent']}/seed-{row['seed']}/seat-{row['seat']}"
        actors = extracted['profiles'][key]
        profile = next(p for p in actors if p['seat']==row['seat'])
        opposite = next(p for p in actors if p['seat']!=row['seat'])
        grouped[(row['model'], row['opponent'])].append(profile)
        opposite_groups[(row['model'], row['opponent'])].append(opposite)
        seat_groups[(row['model'], row['opponent'], row['seat'])].append(profile)
    pair_profiles = []
    for pair in result['pairs']:
        model, opponent = pair['candidate'], pair['opponent']
        verify_profile_totals(grouped[(model,opponent)], pair['candidate_metrics'])
        verify_profile_totals(opposite_groups[(model,opponent)], pair['opponent_metrics'])
        temporal = aggregate_profiles(grouped[(model, opponent)])
        pair_profiles.append(dict(model=model, opponent=opponent, metrics=temporal,
                                  opponent_metrics=aggregate_profiles(opposite_groups[(model,opponent)]),
                                  seats=[dict(seat=t, metrics=aggregate_profiles(seat_groups[(model, opponent, t)])) for t in (0, 1)]))
    common = contract['evaluation']['common_opponents']
    complete = [o for o in common if not any(f['opponent'] == o for f in failures)]
    from scripts.prism_style_atlas import aggregate
    profiles = {}
    for model in ('a', 'base'):
        metrics = aggregate([p['candidate_metrics'] for p in result['pairs'] if p['candidate'] == model and p['opponent'] in complete])
        temporal = aggregate_profiles([x for o in complete for x in grouped[(model, o)]])
        metrics.update(temporal)
        grid = observed_grid(rows, model, complete)
        ranges = {next(r['opponent_identity'] for r in rows if r['opponent'] == o):
                  contract['evaluation']['common_seed_by_opponent'][o] for o in complete}
        profiles[model] = dict(sha256=result['candidate_sha256'][model], rules_sha256=rules,
                               mode='both-greedy', metrics_semantics=policy['metrics_semantics_id'],
                               metrics=metrics, grid=grid, seed_by_opponent=ranges)
    require(profiles['a']['grid'] == profiles['base']['grid'], 'parent descriptive cohort mismatch')
    route = classify_matched_profiles(profiles['a'], profiles['base'], policy)
    deltas = {k: profiles['a']['metrics'][k] - profiles['base']['metrics'][k]
              if type(profiles['a']['metrics'].get(k)) in (int, float) and type(profiles['base']['metrics'].get(k)) in (int, float)
              else None for k in ('low_cards','low_share','big_printed_vp','noble_coverage','vp_main',
                                  'first_big_main','first_big_coverage','early_low_cards','early_discount_redemptions')}
    card = dict(format='prism-candidate-archive-v1', identity=candidate,
                lineage=dict(parent=contract['base_model'], initialization='fresh optimizer/RNG warm-start',
                             training_target='competitive outcome; no added style reward', training_seeds=len(registry['training_rngs'])),
                competitive=dict(frozen=result['per_training_seed'], planned_attempts=result['planned_games'],
                                 completed_games=result['games'], failures=failures,
                                 training_outside_coverage='latest-alpha/latest-balance/parent/general were training opponents',
                                 opponent_changes=[dict(opponent=o, delta_score=next(p['candidate_metrics']['score_rate'] for p in result['pairs'] if p['candidate']=='a' and p['opponent']==o)-next(p['candidate_metrics']['score_rate'] for p in result['pairs'] if p['candidate']=='base' and p['opponent']==o)) for o in common if o!='beta']),
                profile=dict(evidence_level='DESCRIPTIVE', scope='post-hoc complete common-opponent subset; original six-opponent gates preserved',
                             opponents=complete, excluded_opponents=[o for o in common if o not in complete],
                             candidate=profiles['a'], parent=profiles['base'], deltas=deltas, per_opponent=pair_profiles),
                route_recommendation=route,
                uses=['下一段主线训练的父候选（新合同待定）', '后续评测候选', '描述性行为研究'],
                publication=dict(published=result['published'], default_replaced=result['default_replaced'], deployed=False,
                                 evidence='source result plus owner authorization; this archive allocates no release version'),
                delivery=dict(offline_pipeline='PASS', visual='PENDING', all_sync='PENDING_FETCH_FAILED',
                              remaining=['下一轮需单独冻结并授权', '固定Balance v0.2.0同网格风格参照缺失']),
                sources={k:dict(path=v['path'],sha256=v['sha256']) for k,v in spec['inputs'].items()},
                replay_audit=dict(path=str((rawroot.parent/'replay-profile-verification.json').relative_to(root)),
                                  sha256=digest(rawroot.parent/'replay-profile-verification.json'),
                                  status=extracted['verify_receipt']['status'], games=extracted['verify_receipt']['games_verified']),
                new_games=0, next_allowed_action='Review this archive; await next-round decision')
    out = root / spec['output_prefix']
    write_json(out.with_suffix('.json'), card)
    render(card, out)
    receipt = dict(format='prism-candidate-archive-receipt-v1', spec_sha256=digest(spec_path),
                   source_sha256={str(Path(__file__).relative_to(ROOT)):digest(__file__),
                                  'scripts/prism_replay_profile.py':digest(root/'scripts/prism_replay_profile.py')},
                   outputs={str(p.relative_to(root)):digest(p) for p in [out.with_suffix(s) for s in ('.json','.md','.html')]},
                   raw_games_verified=len(rows), planned_entries_verified=len(rows)+len(failures),
                   raw_WDL_seats_verified=True, projected_own_main_and_purchases_verified=True,
                   original_results_unchanged=digest(sources['result'])==spec['inputs']['result']['sha256'],
                   status='PASS_OFFLINE_ARCHIVE', new_games=0)
    write_json(out.with_suffix('.receipt.json'), receipt)
    return card, receipt


def render(card, prefix):
    a, b, d = card['profile']['parent']['metrics'], card['profile']['candidate']['metrics'], card['profile']['deltas']
    metrics = [('低分牌占比','low_share','%',100), ('大牌印刷分/局','big_printed_vp','VP/局',1),
               ('贵族覆盖','noble_coverage','%',100), ('得分效率','vp_main','VP/本人Main',1),
               ('首次4–5VP购牌条件时点','first_big_main','本人Main',1), ('4–5VP购牌覆盖','first_big_coverage','%',100),
               ('前12Main低分牌购入','early_low_cards','张/局',1), ('前24Main早期投资折扣兑现','early_discount_redemptions','单位/局',1)]
    def rounded(x, decimals=4):
        return str(Decimal(str(x)).quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP))
    fmt = lambda x, scale=1: 'NOT_MEASURED' if x is None else rounded(x*scale)
    stat = card['competitive']['frozen']['a']['direct_parent']
    n = b['games']
    intro = [f"# {card['identity']['label']} · 候选产物卡", '',
             '产物：最终c20权重及父代、审计、原结果和保存回放已绑定。', '',
             f"竞技：对父代半平 {rounded(100*stat['mean'],2)}%，95%区间 [{rounded(100*stat['ci95'][0],2)}, {rounded(100*stat['ci95'][1],2)}]%；直接增强门通过。原共同池门仍缺1个基线终局。", '',
             '风格：相对父代的变化为事后描述；固定Balance v0.2.0同网格参照缺失，路线待定。', '',
             f"匹配画像：五个完整共同对手，每代 {n} 局；排除整个Beta对手，不替代原六对手门。", '',
             '| 指标 | 父代 | M75 c20 | 变化 | 单位 |', '| --- | ---: | ---: | ---: | --- |']
    table_rows = []
    for label,key,unit,scale in metrics:
        values = [label,fmt(a.get(key),scale),fmt(b.get(key),scale),fmt(d.get(key),scale),
                  '%；变化为pp' if unit=='%' else unit]
        intro.append('| '+' | '.join(values)+' |')
        table_rows.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>')
    coverage_note = f"首次大牌条件时点的分母：父代{a.get('first_big_games','未测')}局、候选{b.get('first_big_games','未测')}局；覆盖分母各{n}局。兑现窗口走到24Main的覆盖：父代{fmt(a.get('early_discount_horizon_coverage'),100)}%、候选{fmt(b.get('early_discount_horizon_coverage'),100)}%；短局按实际终局停止。"
    intro += ['', coverage_note, '', '时点只在实际买入4–5VP牌的局中求均值，覆盖分母为全部完整局。前12/24Main窗口在终局停止，短局不补虚构动作。兑现为实际后续购牌中的早期低分牌折扣贡献，按既有每投资3/每局24封顶规则；属于描述性归属，不作因果解释。', '',
              '用途：'+'；'.join(card['uses'])+'。', '', '状态：未发布、未默认替换、未部署。', '',
              '旧锚点变化：'+ '；'.join(f"{x['opponent']} {x['delta_score']*100:+.2f}pp" for x in card['competitive']['opponent_changes'])+'。', '',
              '公式：半平=(胜+0.5×平)/局数；低分占比=Σ0–1VP购牌/Σ购牌；大牌印刷分=Σ3–5VP印刷分/局数；VP/Main=Σ本人终局VP/Σ本人Main。', '',
              '画像证据及逐对手/座位数据见同名JSON；身份输入SHA见同名receipt。下一轮等待用户决定。']
    prefix.with_suffix('.md').write_text('\n'.join(intro)+'\n',encoding='utf-8')
    esc = html.escape
    blocks = ''.join('<p>'+esc(p)+'</p>' for p in intro[2:10] if p)
    sha = esc(card['identity']['sha256'])
    names={'a':'M75 c20','base':'Balance v0.2.3','alpha':'Alpha v0.1.4','balance':'Balance v0.1.0','beta':'Beta v0.1.0','general':'Prism v0.1.1','heuristic':'Heuristic v0.3.1','released-alpha':'Alpha v0.1.5','latest-alpha':'Alpha v0.2.0','latest-balance':'Balance v0.2.1','parent':'Balance v0.2.3'}
    details = ''.join('<tr><td>'+esc(names.get(p['model'],p['model']))+'</td><td>'+esc(names.get(p['opponent'],p['opponent']))+'</td><td>'+str(p['metrics']['games'])+'</td><td>'+fmt(p['metrics'].get('first_big_main'))+'</td><td>'+fmt(p['metrics'].get('early_low_cards'))+'</td><td>'+fmt(p['metrics'].get('early_discount_redemptions'))+'</td></tr>' for p in card['profile']['per_opponent'])
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M75 候选产物卡</title>
<style>body{margin:0;background:#f2f5fa;color:#172a40;font:16px/1.65 system-ui,sans-serif}main{max-width:1080px;margin:32px auto;padding:24px}section{background:white;padding:24px;margin:20px 0;border-radius:12px}h1{font-size:32px}h2{font-size:22px}.hash{overflow-wrap:anywhere;font:13px/1.6 monospace}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:700px;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:10px;border-bottom:1px solid #dce4ef}th{background:#eef3fa}a{color:#245ec0}summary{cursor:pointer;font-weight:600}.status{border-left:4px solid #3565c8;padding-left:16px}@media(max-width:600px){main{margin:0;padding:14px}section{padding:16px}h1{font-size:26px}}</style>
<main><h1>M75 c20 · 候选产物卡</h1><p><a href="m75-prism-continuation-comparison-r4.html">竞技阅读报告</a> · <a href="m75-prism-continuation-curve-r2.html">开发曲线</a> · <a href="reports.html">报告索引</a></p>
<section class="status">'''+blocks+'''</section><section><h2>身份与用途</h2><p class="hash">SHA256 '''+sha+'''</p><p>父代：Prism Balance v0.2.3；fresh optimizer/RNG warm-start；1个训练seed。</p><p>'''+esc('；'.join(card['uses']))+'''</p><p>未发布 · 未默认替换 · 未部署 · 下一轮等待决定</p></section><section><h2>相对父代的匹配画像</h2><p>五个完整共同对手，每代 '''+str(n)+''' 局。原六对手门及Beta基线缺项保留。</p><div class="scroll"><table><tr><th>指标</th><th>父代</th><th>M75 c20</th><th>变化</th><th>单位</th></tr>'''+''.join(table_rows)+'''</table></div><p>首次大牌时点只在买到4–5VP牌的局中求均值，同时展示覆盖率。前12/24本人Main在终局停止；真实折扣兑现按每投资3、每局24单位封顶。详细公式和分母见JSON。</p></section>
<section><h2>路线与处置</h2><p>路线待定，证据等级 INSUFFICIENT；相对父代行为证据为 DESCRIPTIVE。固定Balance v0.2.0同网格画像缺失。</p><p>'''+esc(coverage_note)+'''</p><p>'''+esc(intro[-5])+'''</p><details><summary>逐对手完整画像</summary><div class="scroll"><table><tr><th>模型</th><th>对手</th><th>局数</th><th>首次大牌Main</th><th>早期低分牌/局</th><th>兑现/局</th></tr>'''+details+'''</table></div></details><p><a href="'''+prefix.name+'''.json">完整JSON与座位分母</a> · <a href="'''+prefix.name+'''.md">Markdown</a> · <a href="'''+prefix.name+'''.receipt.json">来源回执</a></p></section></main></html>'''
    prefix.with_suffix('.html').write_text(document, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    args = parser.parse_args()
    _, receipt = build(args.spec)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
