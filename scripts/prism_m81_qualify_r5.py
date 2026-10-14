"""Zero-game qualification against immutable M81 A final-cycle artifacts."""
import hashlib
import io
import json
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def qualify():
    import inspect
    import torch
    from scripts import prism_m81_performance_r5 as adapter
    from scripts.prism_seal_storage_fast import SealScope, ledger_payload_bytes
    from scripts.prism_m67_storage import install as compressed
    from training.prism_portable.common import read, write, digest
    from training.prism_portable.engine.ppo.store import CommitStore, json_bytes
    from training.prism_portable.engine.ppo.contract import PPOConfig
    from training.prism_portable.engine.ppo.learner import prepare_batch, validate_batch
    from training.prism_portable.engine.ppo import arena
    from scripts import prism_dsw_ppo_process as process

    torch.set_num_threads(1)
    module = adapter.install(); module.verify(); module.install_resource_mode(); compressed()
    campaign = ROOT/'campaigns/A'
    before = {p: digest(campaign/p/'HEAD.json') for p in ('run', 'launch-ledger')}
    def load(part):
        head = read(campaign/part/'HEAD.json')
        commit = read(campaign/part/'commits'/(head['commit']+'.json'))
        store = CommitStore(campaign/part, head['identity'])
        return store, store.get_payload(commit['payload'])
    store, state = load('run'); _, ledger = load('launch-ledger')
    config = PPOConfig.from_dict(read(campaign/'contract.json')['run']['ppo'])
    games = [store.get_json(state['jobs'][j['job_id']]['artifact']) for j in state['schedule']]
    behavior = SimpleNamespace(identity=games[0]['behavior_id'], catalog=games[0]['catalog_fingerprint'],
                               model=SimpleNamespace(style_enabled=False))
    rng = torch.get_rng_state().clone()
    started = time.perf_counter()
    old = prepare_batch(games[:8], behavior, config, max_decisions=200000, verify=False)
    validate_batch(old, config); old_bytes = json_bytes(old)
    baseline_seconds = time.perf_counter()-started
    started = time.perf_counter()
    with SealScope().installed():
        new = prepare_batch(games[:8], behavior, config, max_decisions=200000, verify=False)
        validate_batch(new, config)
        from training.prism_portable.engine.ppo import store as store_module
        new_bytes = store_module.json_bytes(new)
    fast_seconds = time.perf_counter()-started
    assert old_bytes == new_bytes
    del old, new, old_bytes, new_bytes

    started = time.perf_counter(); scope = SealScope()
    with scope.installed():
        batch = prepare_batch(games, behavior, config, max_decisions=200000, verify=False)
        validate_batch(batch, config)
        encoded = store_module.json_bytes(batch)
        # The legacy binding helper revalidates this same in-memory batch.
        validate_batch(batch, config)
    complete_seconds = time.perf_counter()-started
    assert hashlib.sha256(encoded).hexdigest() == state['batch']
    binding = read(campaign/'cycle-20-batch-binding.json')
    assert batch['batch_id'] == binding['batch_id']
    assert torch.equal(rng, torch.get_rng_state())

    ledger_times = []
    for _ in range(3):
        started = time.perf_counter(); raw = io.BytesIO(); torch.save(ledger, raw)
        old_seconds = time.perf_counter()-started
        started = time.perf_counter(); fast = ledger_payload_bytes(ledger)
        new_seconds = time.perf_counter()-started
        assert raw.getvalue() == fast
        ledger_times.append(dict(original_seconds=old_seconds, optimized_seconds=new_seconds))
    del games, batch, encoded, ledger, raw, fast

    fake = SimpleNamespace(root=campaign, spec=read(campaign/'contract.json'),
                           run=SimpleNamespace(state=state, submit=lambda: None, seal=lambda: None))
    adapter.setup(fake)
    assert fake._qualified_native.__globals__['ProcessTree'] is process.ProcessTree
    assert fake._qualified_native.__globals__['directory_bytes'].__self__ is fake._performance_storage
    assert module.worker.__globals__['install_campaign'] is adapter.setup
    fake.run.seal()
    fake._performance_storage.reconcile()
    fake._performance_publications.__exit__(None, None, None)
    assert before == {p: digest(campaign/p/'HEAD.json') for p in before}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = dict(status='PASS', new_games=0, forwards=0, optimizer_updates=0,
                  complete_games=256, batch_object_sha256=state['batch'],
                  historical_batch_bytes_exact=True, historical_ledger_bytes_exact=True,
                  rng_unchanged=True, heads_unchanged=True,
                  eight_game_old_seconds=baseline_seconds, eight_game_new_seconds=fast_seconds,
                  complete_prepare_validate_encode_revalidate_seconds=complete_seconds,
                  seal_cache=scope.metrics, ledger_trials=ledger_times,
                  cpu_seconds=usage.ru_utime+usage.ru_stime, observed_at=time.time())
    write(adapter.REV/'qualification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__': qualify()
