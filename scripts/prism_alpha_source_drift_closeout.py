"""Record live workspace drift without altering the frozen M56 runtime or result."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from prism_alpha_readability_revision import ROOT, ART, RESULT, read, sha


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    assert read(ART / 'controller-status.json')['state'] == 'COMPLETE'
    assert not (ART / 'source-drift-docs-correction.json').exists()
    result_sha = sha(RESULT)
    control = read(ART / 'controller-contract.json')
    assert all(sha(ROOT / n) == h for n, h in control['files'].items())
    build = read(ART / 'build-provenance.json')
    changed = []
    for name, old in build['source_files'].items():
        p = ROOT / name
        current = sha(p)
        if current != old:
            changed.append({'path': name, 'build_snapshot_sha256': old, 'current_sha256': current,
                            'mtime_utc': datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    allowed = {'crates/splendor-cli/src/human_play_command.rs', 'crates/splendor-cli/tests/studio_registry.rs'}
    assert {x['path'] for x in changed} == allowed
    assert not (allowed & set(control['files']))
    write(ART / 'closeout-audit-attempt-1.json', {
        'status': 'FAIL', 'command': 'python -B scripts/prism_alpha_closeout.py', 'exit_code': 1,
        'failure': 'ValueError: build source crates/splendor-cli/src/human_play_command.rs',
        'scope': 'strict comparison of all 305 current Rust/Cargo files against post-build snapshot',
        'frozen_runtime_inputs_checked_before_failure': 76,
        'resolution': 'retain failed check; record two non-frozen live source drifts separately; verify all frozen runtime inputs unchanged',
        'new_games': 0})
    write(ART / 'post-build-source-drift.json', {
        'status': 'DRIFT_DETECTED', 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'snapshot_sources': len(build['source_files']), 'unchanged_sources': len(build['source_files']) - len(changed),
        'changed_sources': changed, 'frozen_runtime_inputs': 76, 'frozen_runtime_inputs_unchanged': True,
        'review_scope': 'current human review dispatch/UI and Studio test; no overwrite or rebuild; current git diff is against HEAD, not the saved pre-build contents',
        'result_sha256_unchanged': result_sha,
        'limitation': 'current whole-workspace source is not byte-identical to the build snapshot; no current-source Studio/UI acceptance claim',
        'new_games': 0})
    primary = ROOT / 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md'
    model = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json'
    documents = [ROOT / p for p in ('docs/m56-prism-alpha-bigcard-ppo.md',
        'docs/aran-model-evolution-matrix.md', 'docs/m51-prism-model-line.md')]
    handoff = ROOT / 'handoff.md'
    snapshots = ART / 'source-drift-docs-snapshot'; snapshots.mkdir()
    originals = {}
    for p in [primary, model, *documents, handoff]:
        originals[str(p.relative_to(ROOT))] = sha(p)
        shutil.copyfile(p, snapshots / p.name)
    note = ('\n\n源码工作区口径补充：收口首次严格比较构建后305文件快照时FAIL；现时303份一致，'
            '人机审阅入口`crates/splendor-cli/src/human_play_command.rs`和测试`crates/splendor-cli/tests/studio_registry.rs`'
            '在运行期间变化（不属于M56冻结输入）。本轮76项冻结输入、实际比赛程序、离线回放指标程序与权重hash均一致，'
            '因此本轮竞技结果仍绑定原冻结运行身份；不能声称当前整仓源码未变，也没有对当前Studio界面/审阅入口重新编译或验收。'
            '本轮固定身份是权重与模型登记记录；界面是否正确加载Prism Alpha v0.1.1尚未验证。'
            '失败检查与漂移证据保留在`local-artifacts/prism/alpha-v0.1.1/{closeout-audit-attempt-1,post-build-source-drift}.json`；'
            '没有回退这两份外部改动、重跑比赛或重算原验收。\n')
    text = primary.read_text(encoding='utf-8') + note
    primary.write_text(text, encoding='utf-8')
    body = text.split('\n\n', 1)[1]
    begin, end = '<!-- M56 VERIFIED RESULTS BEGIN -->', '<!-- M56 VERIFIED RESULTS END -->'
    for p in documents:
        s = p.read_text(encoding='utf-8')
        a, b = s.index(begin), s.index(end) + len(end)
        old = s[a + len(begin):b - len(end)].strip()
        prefix = old.split('\n', 1)[0] + '\n\n' if old.startswith('## M56 ') else ''
        p.write_text(s[:a] + begin + '\n\n' + prefix + body + '\n\n' + end + s[b:], encoding='utf-8')
    identity = read(model); identity['readable_report_sha256'] = sha(primary)
    write(model, identity)
    handoff.write_text(handoff.read_text(encoding='utf-8') +
        '\n\n### M56 收口审计补充（2026-10-03）\n\n'
        '首次305构建快照严格现时匹配FAIL，303一致、两份未冻结的人机审阅/Studio测试文件变化；'
        '76冻结运行输入与原结果不变。完整记录见M56和`post-build-source-drift.json`；当前Studio对新Alpha模型的加载未验收，'
        '不以本轮离线竞技结论替代界面验收。保留外部改动，0新局/更新。\n', encoding='utf-8')
    assert sha(RESULT) == result_sha
    assert all(sha(ROOT / n) == h for n, h in control['files'].items())
    write(ART / 'source-drift-docs-correction.json', {'status': 'PASS', 'original_snapshots': originals,
        'result_sha256_unchanged': result_sha, 'report_sha256': sha(primary), 'model_sha256': sha(model),
        'new_games': 0, 'new_training_steps': 0, 'strict_source_comparison': 'FAIL_RETAINED',
        'frozen_runtime_contract': 'PASS_UNCHANGED', 'current_source_drifts': sorted(allowed)})
    print('Recorded: strict source comparison FAIL retained; 303/305 snapshot matches, 2 non-frozen drifts; all 76 runtime inputs unchanged.')


if __name__ == '__main__':
    main()
