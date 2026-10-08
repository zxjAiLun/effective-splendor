"""Verify the real, completed M56 readable page against its immutable result."""
import hashlib
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local-artifacts/prism/alpha-v0.1.1'
PAGE = ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.html'
RESULT = ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.result.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def values(group, metric, profile):
    cards = metric['mean_cards_by_vp']
    if group == 'big':
        return [metric['score_rate'] * 100, *[cards[str(v)] for v in (3, 4, 5)],
                sum(cards[str(v)] for v in (3, 4, 5)),
                sum(v * cards[str(v)] for v in (3, 4, 5)),
                metric['mean_prestige'], metric['vp_per_main_action']]
    if group == 'economy':
        return [metric['mean_permanent_bonuses'], metric['mean_nobles'],
                metric['games_with_nobles_percent'], metric['mean_reserves_acquired'],
                metric['mean_reserves_bought'], metric['mean_reserves_stranded'],
                metric['reserve_redemption_rate_percent']]
    if group == 'cards':
        return [cards[str(v)] for v in range(6)]
    rows = [profile['mean_total_vp_auc24'], profile['mean_large_card_vp_auc24'],
            profile['first_large_card_main']['conditional_mean'],
            100 * profile['first_large_card_main']['coverage_rate']]
    for checkpoint in profile['score_checkpoints']:
        rows += [checkpoint['mean_vp'], checkpoint['mean_large_card_printed_vp']]
    return rows


def main():
    assert read(ART / 'controller-status.json')['state'] == 'COMPLETE'
    assert read(ART / 'human-docs-correction.json')['status'] == 'PASS'
    result = read(RESULT)
    result_hash, html_hash = sha(RESULT), sha(PAGE)
    checks, errors = [], []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    groups = ('big', 'economy', 'cards', 'trajectory')
    common = ('heuristic-v031', 'prism-v01', 'prism-v0.1.1')
    started = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 1000}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(PAGE.as_uri(), wait_until='load')
        check(page.locator('h1').inner_text().startswith('Prism Alpha v0.1.1'), 'real version heading')
        check('SYNTHETIC' not in page.locator('main').inner_text(), 'no fixture data banner')
        check(page.locator('#result tbody tr').count() == 8, 'default big-card eight rows')
        check(page.locator('.cards .card b').first.inner_text() ==
              ('PASS' if result['all_three_gates_passed'] else '未通过'), 'real gate verdict')
        check(page.locator('a').first.get_attribute('href') ==
              'prism-alpha-v0.1.1-evaluation-summary.md', 'full Markdown report link')
        check(page.locator('#groups button').count() == 4, 'four metric groups')
        for stage_index, stage in enumerate(('acceptance', 'development')):
            page.locator('#stages button').nth(stage_index).click()
            opponents = common + (('base-t1',) if stage == 'acceptance' else ())
            check(page.locator('#opponents button').count() == len(opponents), stage + ' eligible opponents')
            for opponent_index, opponent in enumerate(opponents):
                page.locator('#opponents button').nth(opponent_index).click()
                pairs = result[stage]['pairs']
                if opponent == 'base-t1':
                    pair = next(x for x in pairs if x['opponent'] == opponent)
                    left, right = pair['opponent_metrics'], pair['candidate_metrics']
                    lp, rp = pair['opponent_bigcard'], pair['candidate_bigcard']
                else:
                    base = next(x for x in pairs if x['opponent'] == opponent and x['candidate'] == 'base')
                    candidate = next(x for x in pairs if x['opponent'] == opponent and x['candidate'] == 'candidate')
                    left, right = base['candidate_metrics'], candidate['candidate_metrics']
                    lp, rp = base['candidate_bigcard'], candidate['candidate_bigcard']
                for group_index, group in enumerate(groups):
                    page.locator('#groups button').nth(group_index).click()
                    a, b = values(group, left, lp), values(group, right, rp)
                    rows = page.locator('#result tbody tr')
                    check(rows.count() == len(a) == len(b), f'{stage}/{opponent}/{group} row count')
                    for i, (x, y) in enumerate(zip(a, b)):
                        cells = rows.nth(i).locator('td')
                        for column, value in ((1, x), (2, y)):
                            actual = cells.nth(column).inner_text()
                            check(actual == 'NOT_APPLICABLE' if value is None else
                                  abs(float(actual.removesuffix('%')) - value) <= 0.000051,
                                  f'{stage}/{opponent}/{group}/{i} player {column} matches result')
                        delta = None if x is None or y is None else y - x
                        expected_class = 'up' if delta is not None and delta > 0 else 'down' if delta is not None and delta < 0 else ''
                        check(cells.nth(3).get_attribute('class') == expected_class,
                              f'{stage}/{opponent}/{group}/{i} numeric direction')
        # Return the delivered preview to the default independent common-opponent view.
        page.locator('#stages button').nth(0).click()
        page.locator('#opponents button').nth(0).click()
        page.locator('#groups button').nth(0).click()
        desktop = ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.png'
        page.screenshot(path=str(desktop), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        check(page.locator('#result tbody tr').count() == 8, 'mobile retains measured rows')
        check(page.locator('body').evaluate('e => e.scrollWidth <= 390'), 'mobile page fits viewport with scrollable table')
        mobile = ART / 'comparison-mobile.png'
        page.screenshot(path=str(mobile), full_page=True)
        check(not errors, 'no browser JavaScript errors')
        browser.close()
    check(sha(RESULT) == result_hash and sha(PAGE) == html_hash, 'UI verification leaves result and page unchanged')
    receipt = {'status': 'PASS', 'checks': len(checks), 'check_labels': checks,
               'result_sha256': result_hash, 'html_sha256': html_hash,
               'desktop_path': str(desktop.relative_to(ROOT)), 'desktop_sha256': sha(desktop),
               'mobile_path': str(mobile.relative_to(ROOT)), 'mobile_sha256': sha(mobile),
               'elapsed_wall_seconds': time.monotonic() - started,
               'errors': errors, 'new_games': 0, 'new_training_steps': 0,
               'scope': 'real local-file HTML; all 28 stage/opponent/group views and displayed player values'}
    (ART / 'browser-validation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS：真实报告28种视图与{len(checks)}项页面/数值核验；桌面/手机截图已保存，0新对局。')


if __name__ == '__main__':
    main()
