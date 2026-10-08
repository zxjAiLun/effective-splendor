"""Generate notebook arena report for recovered arena with retained gaps (e.g. 29995/30000 games).

Computes Rust s4_batch_metrics across all 29995 complete games, runs paired bootstrap on
complete seed blocks (14995 pairs), records the 5 missing games as retained gaps, and
publishes verified result.json, report.md, report.html, completion.json and source-ledger.json.
"""
from collections import Counter, defaultdict
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import markdown
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_match_details as details
from scripts import prism_notebook_arena as arena
from scripts import prism_notebook_report as report_orig
from scripts import prism_ppo_fixed_eval as fixed
from training.prism_portable.common import read, write, digest

sha = digest
require = fixed._require


def safe_interval(rows, pure=False):
    paired = defaultdict(dict)
    for r in rows:
        require(r['candidate_seat'] not in paired[r['seed']], 'duplicate paired seat')
        paired[r['seed']][r['candidate_seat']] = float(r['record'] == 'win') if pure else r['candidate_score']
    complete_blocks = [sum(v.values()) / 2 for _, v in sorted(paired.items()) if set(v) == {0, 1}]
    blocks = np.array(complete_blocks)
    rng = np.random.default_rng(64049999)
    width = max(1, min(128, 1024 * 1024 // len(blocks)))
    samples = []
    for start in range(0, 20000, width):
        samples.extend(blocks[rng.integers(0, len(blocks), (min(width, 20000 - start), len(blocks)))].mean(1))
    return dict(
        estimate=float(blocks.mean()),
        ci95=np.quantile(samples, [.025, .975]).tolist(),
        seed_blocks=len(blocks),
        incomplete_seeds=len(paired) - len(blocks),
        samples=20000,
        seed=64049999,
        scope='descriptive paired seed bootstrap on complete pairs; incomplete pairs excluded from block diff'
    )


def collect_recovery(work, plan, state):
    groups = defaultdict(list)
    ledger = []
    validated_config = arena.validate_arena_config(read(work / 'config.json'), work / 'config.json')
    catalog_fingerprint = validated_config['config']['catalog_fingerprint']
    missing_games = []

    for shard in plan['shards']:
        name = shard['name']
        s_receipt = state['shards'][name]
        out = Path(shard['output'])
        cp = Path(shard['config'])
        v = arena.validate_arena_config(read(cp), cp)
        progress = read(out / 'progress.json')

        for record in progress['games'].values():
            if record.get('status') != 'completed':
                missing_games.append(record.get('game_id'))
                continue
            row = record['row']
            p = out / 'games' / row['candidate'] / row['opponent'] / f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            replay = read(p / 'replay.json')
            report = read(p / 'report.json')
            proc = read(p / 'process-result.json')
            game = read(p / 'game.json')
            config = read(p / 'match-config.json')

            require(fixed.canonical_hash(config) == game['game_config_sha256'], 'match config drift')
            verified = fixed._report_result(report, replay, game_id=game['game_id'], seed=row['seed'], seat=row['candidate_seat'], catalog=catalog_fingerprint)
            require(all(row[k] == verified[k] for k in verified), 'saved row differs from verified terminal result')
            require(proc['returncode'] == 0 and proc['wall_seconds'] > 0, 'invalid observed game clock')

            row = dict(row)
            row['_candidate_actions'], row['_opponent_actions'] = Counter(), Counter()
            for step in replay['steps']:
                row['_candidate_actions' if step['actor'] == row['candidate_seat'] else '_opponent_actions'][step['action']['type']] += 1
            row.update(_wall_seconds=proc['wall_seconds'], _replay_path=str(p / 'replay.json'))
            groups[(row['candidate'], row['opponent'], row['candidate_seat'])].append(row)
            ledger.append(dict(
                game=str(p / 'game.json'),
                hashes={n: sha(p / n) for n in ('game.json', 'report.json', 'replay.json', 'process-result.json', 'match-config.json')}
            ))

    expected_games = state['completed_games']
    require(len(ledger) == expected_games, f'ledger count mismatch: {len(ledger)} vs expected {expected_games}')
    write(work / 'source-ledger.json', ledger)

    metrics = {}
    audits = work / 'metrics'
    audits.mkdir(exist_ok=True)
    for index, (key, rows) in enumerate(sorted(groups.items())):
        manifest = audits / f'group-{index:04d}.manifest.json'
        output = audits / f'group-{index:04d}.metrics.json'
        write(manifest, dict(rows=[dict(replay_path=r['_replay_path']) for r in rows]))
        argv = [plan['metrics_program']['path'], str(manifest), str(output)]
        started = time.monotonic()
        p = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        write(audits / f'group-{index:04d}.receipt.json', dict(
            argv=argv, exit_code=p.returncode, wall_seconds=time.monotonic() - started,
            stdout=p.stdout, stderr=p.stderr, manifest_sha256=sha(manifest)
        ))
        require(p.returncode == 0, 'Rust rules replay verification failed: ' + p.stderr)
        metrics[key] = read(output)

    pairs = []
    for model, opponent in sorted({(m, o) for m, o, _ in groups}):
        rows = groups[(model, opponent, 0)] + groups[(model, opponent, 1)]
        cb, ob, seats = [], [], []
        for seat in (0, 1):
            rs = groups[(model, opponent, seat)]
            raw = metrics[(model, opponent, seat)]
            c = raw['seat_p0_first' if seat == 0 else 'seat_p1_second']
            o = raw['seat_p1_second' if seat == 0 else 'seat_p0_first']
            cb.append((c, len(rs)))
            ob.append((o, len(rs)))
            seats.append(dict(
                candidate_seat=seat,
                candidate=details.merge_player([(c, len(rs))], rs, True),
                opponent=details.merge_player([(o, len(rs))], rs, False)
            ))
        pairs.append(dict(
            candidate=model, opponent=opponent,
            candidate_metrics=details.merge_player(cb, rows, True),
            opponent_metrics=details.merge_player(ob, rows, False),
            seats=seats, macro=details.macro(rows),
            win_ci=safe_interval(rows, True), score_ci=safe_interval(rows)
        ))

    return pairs, missing_games


def build_recovery_report(work):
    work = Path(work).resolve()
    plan = read(work / 'plan.json')
    state = read(work / 'status.json')
    pairs, missing_games = collect_recovery(work, plan, state)

    config = read(work / 'config.json')
    lines = [
        '# Prism 通用对战结果（DSW / SSH - 已恢复带缺项）', '',
        f'**产物：已完成 {state.get("completed_games")} 局，Rust规则回放验核与双方指标守恒通过。有 {len(missing_games)} 个保留缺项（步数安全限制死锁或孤立中断），未自动重试，未捏造平局。**', '',
        '**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，保留缺项未执行完整晋级。', '',
        '**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。', '',
        '候选按用户声明的完整模型名及导出SHA识别。', '',
        '## 候选匹配比较', ''
    ]

    for p in pairs:
        m, o = p['candidate'], p['opponent']
        a, b = p['candidate_metrics'], p['opponent_metrics']
        macro = p['macro']
        lines += [
            '', f"## {plan['candidates'][m]['display_name']} 对阵 {plan['opponents'][o]['display_name']}", '',
            f"被测模型模式：{plan['candidates'][m]['mode']}；对手模式：{plan['opponents'][o]['mode']}。", '',
            report_orig.table(['局数/双座种子块', '胜/平/负', '纯胜率', '半平得分率', '纯胜配对95%CI', '半平配对95%CI'], [[
                f"{a['games']}/{p['score_ci']['seed_blocks']}", f"{a['wins']}/{a['ties']}/{a['losses']}",
                f"{a['win_rate_percent']:.4f}%", f"{100*a['score_rate']:.4f}%",
                ' / '.join(f'{100*x:.4f}%' for x in p['win_ci']['ci95']),
                ' / '.join(f'{100*x:.4f}%' for x in p['score_ci']['ci95'])
            ]]),
            report_orig.table(['模型物理座位', '局数', '胜/平/负', '纯胜%', '半平%', '模型VP/局', '对手VP/局'], [
                [f"P{s['candidate_seat']}（{'先' if s['candidate_seat']==0 else '后'}手）", s['candidate']['games'],
                 f"{s['candidate']['wins']}/{s['candidate']['ties']}/{s['candidate']['losses']}",
                 report_orig.num(s['candidate']['win_rate_percent']), report_orig.num(100*s['candidate']['score_rate']),
                 report_orig.num(s['candidate']['mean_prestige']), report_orig.num(s['opponent']['mean_prestige'])] for s in p['seats']
            ])
        ]
        metrics = [
            ('最终VP/局', 'mean_prestige'), ('VP/本人全部决策', 'vp_per_turn'), ('VP/本人Main', 'vp_per_main_action'),
            ('永久折扣/购卡每局', 'mean_permanent_bonuses'), ('贵族/局', 'mean_nobles'),
            ('获得贵族的对局%', 'games_with_nobles_percent'),
            ('预留获取/局', 'mean_reserves_acquired'), ('预留买回/局', 'mean_reserves_bought')
        ]
        personal = [[label, report_orig.num(a[key]), report_orig.num(b[key])] for label, key in metrics]
        lines.append(report_orig.table(['个人指标', '被测模型', '对手'], personal))

    text = '\n\n'.join(lines) + '\n'
    fixed._atomic_text(work / 'report.md', text)
    body = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    css = 'body{font:16px/1.7 system-ui;color:#183238;background:#f5f8f7;max-width:1200px;margin:auto;padding:30px}h1,h2{color:#135d54}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;background:white}td,th{border:1px solid #d8e3df;padding:9px;text-align:left}th{background:#e8f1ee}'
    fixed._atomic_text(work / 'report.html', f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Prism DSW对战报告</title><style>{css}</style></head><body>{body}</body></html>')

    result = dict(
        format='prism-notebook-arena-result-v1',
        verdict='DEVELOPMENT_ONLY_NOT_PROMOTED',
        formal_acceptance='NOT_RUN',
        style_acceptance='NOT_RUN',
        games=state['completed_games'],
        pairs=pairs,
        retained_gaps=missing_games,
        config_sha256=plan['config_sha256'],
        plan_sha256=sha(work / 'plan.json'),
        source_ledger_sha256=sha(work / 'source-ledger.json'),
        bootstrap=plan['bootstrap'],
        runtime=state.get('resources', {}),
        measured_elapsed_before_report_seconds=time.time() - state.get('started_at', state.get('at', time.time()))
    )
    write(work / 'result.json', result)

    completion = dict(
        status=state['state'],
        plan_sha256=sha(work / 'plan.json'),
        result_sha256=sha(work / 'result.json'),
        report_sha256=sha(work / 'report.md'),
        html_sha256=sha(work / 'report.html'),
        games=state['completed_games'],
        retained_gaps_count=len(missing_games),
        automatic_game_retries=0,
        model_promotion='NOT_RUN'
    )
    write(work / 'completion.json', completion)
    return completion


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'evaluation/a-common-recovery-r3')
    res = build_recovery_report(target)
    print(json.dumps(res, indent=2))
