"""Freeze M56 and create its zero-update run; never launches a match."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_alpha_round import ART, PILOT, TRAIN, CONTROL, read, write, sha, require


def main():
    import torch
    from training.prism.export import load_weights
    from training.prism.ppo.arena import Campaign
    from training.prism.ppo.coordinator import source_identity
    from training.prism.ppo.style import profile_from_after_main
    from training.prism.ppo.execution import validate_spec, check_assets
    pilot, train = read(PILOT), read(TRAIN)
    validate_spec(train); check_assets(train)
    old = read(ROOT / 'local-artifacts/prism/rush-v0.1.0/controller-contract.json')
    for name, digest in old['files'].items():
        require(sha(ROOT / name) == digest, 'old M55 frozen file drift: ' + name)
    exe = ART / 'build/release/examples/prism_bigcard_metrics.exe'
    manifest = ROOT / 'local-artifacts/prism/rush-v0.1.0/fixture-manifest.json'
    profiles = ART / 'fixture-profiles.json'
    subprocess.run([str(exe), str(manifest), str(ART / 'style.json'), str(profiles)], check=True, timeout=120)
    old_profiles = read(ROOT / 'local-artifacts/prism/rush-v0.1.0/fixture-profiles.json')['games']
    actual = read(profiles)['games']
    require(len(actual) == len(old_profiles) == 13, 'saved fixture coverage')
    checks = 0; noble_games = 0
    work = ART / 'fixture-economic'; work.mkdir()
    for i, (new, previous) in enumerate(zip(actual, old_profiles)):
        replay = read(new['replay_path'])
        noble_games += any(s['action']['type'] == 'choose_noble' for s in replay['steps'])
        m, out = work / f'{i}.manifest.json', work / f'{i}.metrics.json'
        write(m, {'rows': [{'replay_path': new['replay_path']}]})
        subprocess.run([str(ROOT / 'local-artifacts/prism/v01/bin/s4_batch_metrics.exe'), str(m), str(out)],
                       check=True, timeout=30, capture_output=True)
        economic = read(out)
        for actor in (0, 1):
            p, old_p = new['profiles'][actor], previous['profiles'][actor]
            require(p['after_main_prestige'] == old_p['after_main_prestige'] and p['main_actions'] == old_p['main_actions'], 'Main/noble curve drift')
            expected = profile_from_after_main(p['after_main_prestige'], p['terminal_prestige'], pilot['style'])
            require(math.isclose(expected['rush_auc'], p['rush_auc'], abs_tol=1e-12), 'Python/Rust AUC24 disagreement')
            require(expected['vp_threshold_by_horizon'] == p['vp_threshold_by_horizon'], 'threshold disagreement')
            require(all(1 <= e['own_main'] <= p['main_actions'] and 0 <= e['printed_vp'] <= 5 for e in p['purchase_events']), 'purchase timestamp range')
            player = economic['seat_p0_first' if actor == 0 else 'seat_p1_second']
            counts = player['mean_cards_by_vp']
            require(all(sum(e['printed_vp'] == vp for e in p['purchase_events']) == counts.get(str(vp), 0) for vp in range(6)), 'whole-game card counts disagree with independent metrics')
            printed = sum(vp * counts.get(str(vp), 0) for vp in (3, 4, 5))
            require(printed == p['terminal_large_card_printed_vp'], 'large VP incorrectly includes nobles or misses cards')
            curve = p['large_card_vp_after_main']
            require(all(curve[k] <= curve[k + 1] for k in range(len(curve) - 1)), 'large VP monotonicity')
            expected_big = sum(min(curve[j] if j < len(curve) else printed, 15) / 15 for j in range(24)) / 24
            require(math.isclose(expected_big, p['large_card_vp_auc24'], abs_tol=1e-12), 'big AUC window/padding disagreement')
            # Independently reconstruct each recorded purchased-card trajectory.
            cumulative = 0
            for main in range(1, p['main_actions'] + 1):
                cumulative += sum(e['printed_vp'] for e in p['purchase_events'] if e['own_main'] == main and e['printed_vp'] >= 3)
                require(curve[main - 1] == cumulative, 'purchase time / curve alignment')
            checks += 9
    write(ART / 'fixture-validation.json', {'status': 'PASS', 'saved_games': 13,
        'games_with_noble_choice': noble_games, 'checks': checks, 'new_games': 0,
        'profiles_sha256': sha(profiles), 'rust_program_sha256': sha(exe), 'manifest_sha256': sha(manifest)})
    require(not CONTROL.exists() and not (ART / 'campaign').exists(), 'M56 preflight already fixed; no reset')
    campaign = Campaign.create(ART / 'campaign', train); run = campaign.run
    parent = load_weights(ROOT / pilot['base_model']['weights_path'], expected_catalog_fingerprint=train['run']['catalog_fingerprint'])
    require(all(torch.equal(v, parent.state_dict()[k]) for k, v in run.learner.model.policy.state_dict().items()), 'warm-start policy/value differs from parent')
    require(run.state['phase'] == 'READY' and run.state['cycle'] == run.state['global_step'] == run.state['attempts'] == 0, 'new run already advanced')
    require(len(run.learner.optimizer.state_dict()['state']) == 0, 'old optimizer moments inherited')
    write(ART / 'initialization-receipt.json', {'status': 'PASS', 'run_identity': run.identity,
        'parent_weights_sha256': sha(ROOT / pilot['base_model']['weights_path']), 'policy_value_tensors_equal_parent': True,
        'optimizer_moments': 0, 'initial_global_step': 0, 'physical_games': 0,
        'fresh_rng_seed': train['run']['seed'], 'new_style_head': True, 'source_identity': source_identity()})
    files = dict(old['files'])
    additions = ['scripts/prism_alpha_round.py', 'scripts/prism_alpha_report.py', 'scripts/prism_alpha_preflight.py',
                 'crates/splendor-cli/examples/prism_bigcard_metrics.rs', 'training/prism/tests/test_alpha_round.py',
                 str(PILOT.relative_to(ROOT)), str(TRAIN.relative_to(ROOT)),
                 str(exe.relative_to(ROOT)), str((ART / 'style.json').relative_to(ROOT)),
                 pilot['base_model']['weights_path'], 'local-artifacts/prism/alpha-v0.1.0/weights.manifest.json']
    for name in additions: files[name] = sha(ROOT / name)
    control = {'format': 'm56-alpha-controller-contract-v1', 'files': files,
        'training_source_identity': source_identity(), 'run_identity': run.identity,
        'no_retry': True, 'only_final_c4': True, 'no_optional_stopping': True,
        'development_selection': False, 'physical_games': 5504, 'workers': 4, 'priority': 'BelowNormal',
        'training_wait_seconds': 14460, 'evaluation_wall_seconds': 7200,
        'worker_cpu_seconds': 1800, 'worker_memory_bytes': 2147483648, 'max_storage_bytes': 68719476736,
        'bootstrap_index_semantics': 'same deterministic resampling index stream per sample length; dual-seat seed is independent block',
        'engineering_validation': {'saved_replays': 13, 'offline_checks': checks, 'rust_tests_passed': 3,
                                   'python_targeted_tests_passed': 24, 'new_matches': 0},
        'next_action': 'bounded four-cycle training, final export, fixed development, once-only independent acceptance and stop'}
    write(CONTROL, control)
    write(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.evaluate.json', control)
    print(json.dumps({'status': 'PASS', 'frozen_files': len(files), 'fixtures': 13,
                      'offline_checks': checks, 'new_matches': 0, 'run_identity': run.identity}, ensure_ascii=False))


if __name__ == '__main__': main()
