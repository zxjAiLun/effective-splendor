import json

from scripts import prism_building_html_report_m63 as html_report


def test_html_report_uses_explicit_paths_and_current_m63_identity(tmp_path):
    markdown = tmp_path / 'm63.md'
    result = tmp_path / 'result.json'
    output = tmp_path / 'named-m63-report.html'
    markdown.write_text(
        '# M63 report\n\n'
        '## 匹配共同锚点：父 → M63 原目标对照 → Prism Beta v0.1.1 candidate\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n'
        '## 十项采样前冻结门\n\n门表\n\n'
        '## 开发与独立方向\n\n无\n\n'
        '## 原验收与增强记录\n\n无\n\n'
        '## 独立验收（9,728局）\n\nNOT_RUN\n\n'
        '## 开发评测（仅描述，576局）\n\nNOT_RUN\n\n'
        '## 来源\n\n无\n', encoding='utf-8')
    result.write_text(json.dumps({'gates': {}, 'verdicts': {}}), encoding='utf-8')

    html_report.main(markdown, result, output)
    rendered = output.read_text(encoding='utf-8')
    assert 'Outcome-Only' not in rendered
    assert '原 building-v1 Control 与 timed-building-v1 Beta' in rendered
    assert 'training seed 63041001' in rendered
    assert f'{markdown.stat().st_size:,} bytes' in rendered
    assert 'M63 原目标对照' in rendered and 'Prism Beta v0.1.1 candidate' in rendered
