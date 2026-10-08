"""Independent M56 artifact consistency audit; no games, training or new looks."""
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_alpha_round import ART, RESULT, PILOT, TRAIN, CONTROL, read, write, sha, require, expected_grid, assert_grid


def main():
    require(read(ART / 'controller-status.json')['state'] == 'COMPLETE', 'audit requires completed finite round')
    result, pilot, control = read(RESULT), read(PILOT), read(CONTROL)
    checks = []
    def check(condition, label):
        require(condition, label); checks.append(label)
    def close(a, b): return math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-9)
    for name, digest in control['files'].items(): check(sha(ROOT / name) == digest, 'frozen ' + name)
    build = read(ART / 'build-provenance.json')
    drift_receipt = read(ART / 'post-build-source-drift.json')
    documented_drift = {x['path']: x for x in drift_receipt['changed_sources']}
    check(set(documented_drift) == {'crates/splendor-cli/src/human_play_command.rs',
                                  'crates/splendor-cli/tests/studio_registry.rs'}, 'explicitly scoped current-source drift')
    unchanged_sources = 0
    for name, digest in build['source_files'].items():
        current = sha(ROOT / name)
        if current == digest:
            check(True, 'build source unchanged ' + name); unchanged_sources += 1
        else:
            entry = documented_drift.get(name)
            check(entry is not None and entry['build_snapshot_sha256'] == digest and entry['current_sha256'] == current
                  and name not in control['files'], 'documented non-frozen source drift ' + name)
    check(unchanged_sources == drift_receipt['unchanged_sources'] == 303, '303 current sources still match build snapshot')
    check(sha(ROOT / 'benchmarks/m55-prism-rush-v0.1.0.result.json') ==
          '9093d26aa1b8a31fd3874b4b79f046bf098755587a49f0eea345e03649bcac57', 'M55 raw negative result retained')
    check(result['config_sha256'] == sha(PILOT) and result['train_sha256'] == sha(TRAIN), 'result/config binding')
    training = result['training']
    check(training['run_identity'] == control['run_identity'], 'new run identity')
    check(training['source_identity'] == control['training_source_identity'], 'training source identity')
    check(training['games'] == 1024 and training['new_steps'] > 0, 'four nonempty PPO cycles')
    check(len(list((ART / 'campaign/attempts').glob('*/completion.json'))) == 1024, 'training physical attempts exactly 1024')
    check(training['final_weights_sha256'] != pilot['base_model']['sha256'], 'new weights differ from parent')
    check(all(s['status'] == 'FINISHED' and s['returncode'] == 0 and s['stop_reason'] is None
              for s in training['supervisor_sessions']), 'clean bounded training termination')
    physical = 1024
    for stage in ('development', 'acceptance'):
        contract = pilot[stage]; plan = read(ART / stage / 'plan.json')
        grid = []
        for shard in plan['shards']:
            cfg = read(shard['config']); out = Path(shard['output'])
            check(sha(shard['config']) == shard['config_sha256'], stage + ' shard config')
            progress = read(out / 'progress.json')
            check(read(out / 'completion.json')['result_sha256'] == sha(out / 'result.json'), stage + ' shard result')
            for g in progress['games'].values():
                check(g['status'] == 'completed', stage + ' terminal game')
                grid.append(g['row'])
        expected = expected_grid(contract['seed_start'], contract['seed_end'])
        if stage == 'acceptance': expected |= expected_grid(contract['seed_start'], contract['direct_seed_end'], True)
        assert_grid(grid, expected); physical += len(grid)
        check(len(grid) == result[stage]['games'] == contract['total_games'], stage + ' full frozen grid')
        source = read(ART / stage / 'source-ledger.json')
        check(len(source) == len(grid), stage + ' ledger coverage')
        for entry in source:
            for name, digest in entry['hashes'].items(): check(sha(Path(entry['path']) / name) == digest, stage + ' immutable ' + name)
        metrics = read(ART / stage / 'match-details.json')
        check(sha(ART / stage / 'match-details.json') == result[stage]['match_details_sha256'], stage + ' details bound')
        check(metrics['verified_replays'] == len(grid), stage + ' all saved replays rule verified')
        for pair in metrics['pairs']:
            n = pair['macro']['total_games']
            check(pair['macro']['decision_latency_ms'] is None and pair['macro']['inference_latency_ms'] is None,
                  stage + ' missing timing stays missing')
            for side in ('candidate', 'opponent'):
                player, big = pair[side + '_metrics'], pair[side + '_bigcard']
                counts = player['action_distribution']; cards = player['mean_cards_by_vp']
                check(player['games'] == big['games'] == n, stage + ' model orientation/count')
                check(player['wins'] + player['ties'] + player['losses'] == n, stage + ' WDL conservation')
                check(close(player['score_rate'], (player['wins'] + .5 * player['ties']) / n), stage + ' half-draw score')
                check(close(player['win_rate_percent'], 100 * player['wins'] / n), stage + ' pure win rate')
                check(close(sum(cards.values()), player['mean_permanent_bonuses']), stage + ' purchased cards/discounts')
                check(close(sum(int(v) * x for v, x in cards.items()) + 3 * player['mean_nobles'], player['mean_prestige']), stage + ' card/noble VP')
                check(close(sum(v * cards[str(v)] for v in (3, 4, 5)), big['mean_terminal_large_card_printed_vp']), stage + ' large-card VP excludes nobles')
                check(sum(counts.values()) == player['total_actor_decisions'], stage + ' action sum')
                check(player['total_main_actions'] == player['total_actor_decisions'] - counts['choose_noble'], stage + ' Main/noble denominator')
                check(close(player['vp_per_main_action'], player['mean_prestige'] * n / player['total_main_actions']), stage + ' summed-denominator velocity')
                check(close(sum(player['action_percentages'].values()), 100), stage + ' action percentage denominator')
                for key in ('first_large_card_main', 'first_4plus_card_main'):
                    c = big[key]; check(close(c['coverage_rate'], c['coverage_games'] / n), stage + ' purchase-time coverage')
                    check(c['conditional_mean'] is None if c['coverage_games'] == 0 else c['conditional_mean'] >= 1,
                          stage + ' conditional time missingness')
                for key in ('wins', 'ties', 'losses', 'total_main_actions', 'total_actor_decisions'):
                    check(player[key] == sum(s[side][key] for s in pair['seats']), stage + ' seat aggregation ' + key)
    check(physical == result['physical_games'] == pilot['acceptance']['total_physical_budget'] == 5504, 'total physical budget')
    check(result['retries'] == 0 and not any(result[k] for k in ('default_replaced', 'shared_pool_deployed', 'git_published')), 'finite scope')
    criteria = {'strength_pool': 'strength_pool_delta_lower_gte', 'direct_parent': 'direct_parent_score_lower_gte',
                'bigcard_auc24': 'bigcard_auc24_delta_lower_gte'}
    check(set(result['gates']) == set(criteria), 'only three frozen gates')
    for k, threshold in criteria.items():
        check(result['gates'][k] == (result['measurements'][k]['simultaneous_one_sided_lower'] >= pilot['acceptance'][threshold]), 'frozen gate decision ' + k)
    check(result['all_three_gates_passed'] == all(result['gates'].values()), 'verdict reflects all floors')
    check(result['acceptance_policy'] == pilot['acceptance'], 'no gate/seed relabeling')
    check(result['measurements']['direct_parent']['seed_blocks'] == 512, 'direct parent 512 paired blocks')
    check(result['measurements']['strength_pool']['seed_blocks'] == 256, 'pooled 256 paired blocks')
    model = read(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json')
    check(model['weights_sha256'] == sha(ROOT / model['weights_path']) == training['final_weights_sha256'], 'canonical model weights')
    check(model['companion_sha256'] == sha(ROOT / model['companion_path']), 'canonical companion')
    check(model['independent_acceptance']['result_sha256'] == sha(RESULT), 'identity/result binding')
    check(model['readable_report_sha256'] == sha(ROOT / model['readable_report']), 'identity/readable report binding')
    check(model['colored_comparison_sha256'] == sha(ROOT / model['colored_comparison_path']), 'identity/colored report binding')
    browser = read(ART / 'browser-validation.json')
    human = read(ART / 'human-docs-correction.json')
    check(browser['status'] == human['status'] == 'PASS', 'readable and browser verification completed')
    check(browser['result_sha256'] == human['result_sha256_unchanged'] == sha(RESULT), 'display corrections retain exact result')
    check(browser['html_sha256'] == sha(ROOT / model['colored_comparison_path']), 'browser audited delivered HTML')
    check(browser['new_games'] == human['new_games'] == 0, 'readable audit adds no games')
    for kind in ('desktop', 'mobile'):
        check(sha(ROOT / browser[kind + '_path']) == browser[kind + '_sha256'], 'real preview ' + kind)
    for name in ('docs/m56-prism-alpha-bigcard-ppo.md', 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md',
                 'docs/aran-model-evolution-matrix.md', 'docs/m51-prism-model-line.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        if '<!-- M56 VERIFIED RESULTS BEGIN -->' in text:
            section = text.split('<!-- M56 VERIFIED RESULTS BEGIN -->', 1)[1].split('<!-- M56 VERIFIED RESULTS END -->', 1)[0]
        else:
            section = text
        check('Prism Alpha v0.1.1' in section and 'Prism Alpha v0.1.0' in section, name + ' current model lineage')
        for token in ('胜 / 平 / 负', '全部七类动作', '局均购入 5 VP卡', '局均 蓝 折扣',
                      '终局未买回预留', 'NOT_MEASURED', '双座明细', '大牌购入时点'):
            check(token in section, name + ' complete current Markdown table ' + token)
        check(not re.search(r'\b(?:011|010)\b', section), name + ' full human version names')
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', text if name.startswith('docs/m56-') else section):
            link = unquote(target.strip('<>').split('#', 1)[0])
            if not link or '://' in link:
                continue
            check(((ROOT / name).parent / link).exists(), name + ' link ' + link)
    milestone = (ROOT / 'docs/m56-prism-alpha-bigcard-ppo.md').read_text(encoding='utf-8')
    check(f"Status: **{result['status']} / VERIFIED**" in milestone, 'current milestone status reconciled')
    for args in (['git', 'diff', '--check'], ['git', 'check-ignore', '-v', 'handoff.md'],
                 ['git', 'check-ignore', '-v', 'local-artifacts/prism/alpha-v0.1.1']):
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        check(p.returncode == 0, 'publication ' + ' '.join(args))
    check(subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=ROOT, text=True).strip() == '', 'staging remains empty')
    check(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == pilot['baseline_git_commit'], 'baseline HEAD unchanged')
    receipt = {'status': 'PASS', 'checks': len(checks), 'check_labels': checks,
               'result_sha256': sha(RESULT), 'model_sha256': sha(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json'),
               'report_sha256': sha(ROOT / model['readable_report']), 'new_games': 0,
               'no_new_statistical_look': True, 'physical_games': physical, 'source_files': len(control['files']),
               'build_source_files': len(build['source_files']), 'live_build_snapshot_status': 'DRIFT_DETECTED',
               'live_build_source_unchanged': unchanged_sources, 'live_build_source_drifts': list(documented_drift),
               'strict_source_snapshot_audit_attempt': 'closeout-audit-attempt-1.json',
               'post_build_source_drift_sha256': sha(ART / 'post-build-source-drift.json'),
               'frozen_runtime_inputs_unchanged': True}
    write(ART / 'final-validation.json', receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != 'check_labels'}, ensure_ascii=False))


if __name__ == '__main__': main()
