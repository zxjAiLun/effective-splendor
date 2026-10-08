"""Clarify final M56 navigation and display. Stored games/gates remain unchanged."""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_alpha_round import ART, ROOT, RESULT, PILOT, read, write, sha, require
from scripts.prism_alpha_report import START, END, replace_block, table


def main():
    require(read(ART / 'controller-status.json')['state'] == 'COMPLETE', 'final output required')
    receipt = ART / 'human-docs-correction.json'
    require(not receipt.exists(), 'readable closeout already finalized')
    result = read(RESULT); original_result_sha = sha(RESULT)
    primary = ROOT / 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md'
    page = ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.html'
    model = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json'
    milestone = ROOT / 'docs/m56-prism-alpha-bigcard-ppo.md'
    matrix = ROOT / 'docs/aran-model-evolution-matrix.md'
    line = ROOT / 'docs/m51-prism-model-line.md'
    handoff = ROOT / 'handoff.md'
    snapshot = ART / 'auto-closeout-snapshot'; snapshot.mkdir()
    originals = {}
    for p in (primary, page, model, milestone, matrix, line, handoff, ART / 'closeout-validation.json'):
        digest = sha(p); destination = snapshot / p.name
        shutil.copyfile(p, destination); originals[str(p.relative_to(ROOT))] = digest
    old_note = '风格两项之外的经济数据为新增描述性指标。'
    new_note = '此表的总VP AUC24/20Main阈值与经济量均为诊断；正式三门是总体棋力、直接父模型和大牌专属AUC24，见原定三门表。'
    for p in (primary, milestone, matrix):
        s = p.read_text(encoding='utf-8').replace(old_note, new_note)
        p.write_text(s, encoding='utf-8')
    text = primary.read_text(encoding='utf-8')
    scope_note = ('\n\n计时负载补充：4是评测worker池上限。开发32个seed块被排成1个384局shard，实际只用1个worker；'
                  '独立验收24个shard使用最多4个并发worker。整批墙钟均按真实运行回执列出，不由并行累计单局时间推算。'
                  '未记录全机CPU占用率或逐决策/推理延迟。训练CPU回执计数范围是受监督worker job，外层Python监督器CPU另计；'
                  '外层高CPU与目录每0.1s扫描的观察见`outer-supervisor-observation.json`及M56，尚无因果profiling结论。\n')
    text += scope_note
    primary.write_text(text, encoding='utf-8')
    headers = ('Status: **AUTHORIZED / NOT_RUN**（新训练、开发、独立验收尚未运行）。',
               'Status: **AUTHORIZED / IMPLEMENTED**；前置核验VERIFIED，训练进行中；开发与独立验收NOT_RUN。',
               'Status: **AUTHORIZED / IMPLEMENTED / TRAINING_VERIFIED**；四轮训练完成，开发与独立验收进行中。')
    current = f"Status: **{result['status']} / VERIFIED**。本有限轮已完成，三门{sum(result['gates'].values())}/3通过；固定实验身份Prism Alpha v0.1.1。"
    s = milestone.read_text(encoding='utf-8')
    header = next((h for h in headers if h in s), None)
    require(header is not None, 'initial milestone header')
    s = s.replace(header, current, 1)
    s = s.replace('## Problem and evidence', '下方启动设计与NOT_RUN表是采样前历史快照；本轮最终结果及完整对战表见后面的M56 VERIFIED RESULTS区块。\n\n## Problem and evidence', 1)
    milestone.write_text(s + scope_note, encoding='utf-8')
    body = text.split('\n\n', 1)[1]
    replace_block(line, '## M56 Prism Alpha v0.1.1实验模型\n\n' + body)
    # Put current experiment navigation above the longer historical matrices.
    for p in (line, matrix):
        s = p.read_text(encoding='utf-8'); first = s.index('\n')
        note = '\n\n当前Alpha实验产物：**Prism Alpha v0.1.1**；本轮' + result['status'] + '，通用Prism v0.1.1身份与默认选择保持原记录。完整新增双方表在本文件M56区块；[彩色对照](prism/prism-alpha-v0.1.1-comparison.html)。\n'
        p.write_text(s[:first] + note + s[first:], encoding='utf-8')
    s = handoff.read_text(encoding='utf-8')
    start = s.index('| M56 Prism Alpha v0.1.1候选 |'); end = s.index('\n', start)
    row = f"| M56 Prism Alpha v0.1.1 | {result['status']}；REGISTERED_EXPERIMENTAL_MODEL | 5,504局0retry；三门{sum(result['gates'].values())}/3通过；固定c4与完整双座/双方表；本有限轮停止 |"
    s = s[:start] + row + s[end:]
    s += ('\n\n### M56 收口资产与下一步\n\n' + table(['资产', '路径 / 含义'], [
        ['精确结果与本轮三门', '`benchmarks/m56-prism-alpha-v0.1.1.result.json`；' + result['status']],
        ['固定实验身份', '`benchmarks/m56-prism-alpha-v0.1.1.model.json`；父模型Prism Alpha v0.1.0'],
        ['当前权重 / companion', '`local-artifacts/prism/alpha-v0.1.1/{weights.json,weights.manifest.json}`'],
        ['完整详细表 / 彩色页', '`docs/prism/prism-alpha-v0.1.1-evaluation-summary.md` / `prism-alpha-v0.1.1-comparison.html`'],
        ['机器/人读收口核验', '`local-artifacts/prism/alpha-v0.1.1/{closeout-validation,final-validation,human-docs-correction,browser-validation}.json`']]) +
        '\n- 本有限轮已停止；后续先profile执行监督的目录扫描开销，再评估目标代理与大牌时点是否相符，预设新目标/预算/种子。性能修改和新训练均未启动；当前没有授权追加训练或默认/共享池部署。\n')
    handoff.write_text(s, encoding='utf-8')
    enhanced = result['confirmed_enhancement']
    summary = '；'.join(k + ('：有校正下界增强证据' if v else '：未建立校正下界增强证据') for k, v in enhanced.items())
    s = page.read_text(encoding='utf-8')
    s = s.replace('<div id="stages">', '<p class="note">通过保留底线与确认增强分别报告。' + summary + '。</p><div id="stages">', 1)
    page.write_text(s, encoding='utf-8')
    identity = read(model)
    identity['readable_report_sha256'] = sha(primary)
    identity['colored_comparison_path'] = str(page.relative_to(ROOT))
    identity['colored_comparison_sha256'] = sha(page)
    write(model, identity)
    require(sha(RESULT) == original_result_sha, 'formal result changed during readable corrections')
    write(receipt, {'status': 'PASS', 'new_games': 0, 'new_training_steps': 0,
        'original_snapshots': originals, 'result_sha256_unchanged': original_result_sha,
        'report_sha256': sha(primary), 'model_sha256': sha(model), 'html_sha256': sha(page),
        'scope': 'navigation, explicit diagnostic-vs-formal labels, actual worker concurrency; no gates/seeds/weights changed'})
    print('PASS：完成当前状态、模型谱系索引、完整表格与时钟负载口径收口；0新对局/更新。')


if __name__ == '__main__': main()
