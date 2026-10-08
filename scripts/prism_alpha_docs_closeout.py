"""Check final M56 documentation and publication state after the artifact audit."""
import json
import re
import subprocess
from urllib.parse import unquote

from prism_alpha_readability_revision import ROOT, ART, RESULT, read, sha


def main():
    checks, commands = [], []
    def check(ok, label):
        assert ok, label
        checks.append(label)
    a, model = read(ART / 'final-validation.json'), read(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json')
    pilot = read(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.config.json')
    for args in (['git', 'diff', '--check'], ['git', 'check-ignore', '-v', 'handoff.md'],
                 ['git', 'check-ignore', '-v', 'local-artifacts/prism/alpha-v0.1.1']):
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        check(p.returncode == 0, ' '.join(args))
        commands.append({'argv': args, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    check(head == pilot['baseline_git_commit'], 'HEAD unchanged')
    check(not subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=ROOT, text=True).strip(), 'staging empty')
    check(not (ART / 'controller.lock').exists(), 'completed controller lock cleaned')
    check(sha(RESULT) == a['result_sha256'], 'result remains frozen')
    check(sha(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json') == a['model_sha256'], 'model registration remains audited')
    check(sha(ROOT / model['readable_report']) == model['readable_report_sha256'] == a['report_sha256'], 'primary report remains audited')
    check(sha(ROOT / model['colored_comparison_path']) == model['colored_comparison_sha256'], 'colored report remains bound')
    documents = ('docs/m56-prism-alpha-bigcard-ppo.md', 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md',
                 'docs/m51-prism-model-line.md', 'docs/aran-model-evolution-matrix.md')
    for name in documents:
        p = ROOT / name
        text = p.read_text(encoding='utf-8')
        section = text if name.startswith(('docs/m56-', 'docs/prism/')) else text.split(
            '<!-- M56 VERIFIED RESULTS BEGIN -->')[1].split('<!-- M56 VERIFIED RESULTS END -->')[0]
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', section):
            link = unquote(target.strip('<>').split('#', 1)[0])
            if link and '://' not in link:
                check((p.parent / link).exists(), name + ' link ' + link)
        check('Prism Alpha v0.1.1' in section and '303' in section and '305' in section, name + ' identity and source scope')
        check(not any(line.endswith((' ', '\t')) for line in section.splitlines()), name + ' new M56 section no trailing whitespace')
    receipt = {'status': 'PASS', 'checks': len(checks), 'check_labels': checks, 'commands': commands, 'HEAD': head,
               'document_sha256': {n: sha(ROOT / n) for n in documents}, 'handoff_sha256': sha(ROOT / 'handoff.md'),
               'new_games': 0, 'new_training_steps': 0, 'result_sha256': a['result_sha256'], 'formal_scope_complete': True,
               'format_scope': 'M56 content only; preserve two historical ASCII diagram whitespace lines 283/291 in the evolution matrix'}
    (ART / 'closure-documentation-check.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS：{len(checks)}项文档、链接、结果绑定与发布策略核验；历史内容保留。')


if __name__ == '__main__':
    main()
