"""Recover c7 presentation artifacts from the exact immutable handoff commit."""
import json
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest
from scripts import prism_m79_deadline_r11 as revision
from scripts import prism_m79_run as run, prism_m79_resume_r7 as r7


def recover():
    revision.verify()
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    run.install()
    r7.install_platform_compatibility()
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.engine.ppo.model import new_model
    from training.prism_portable.engine.ppo.arena import Campaign
    from training.prism_portable.protocol import state_fingerprints
    from training.prism_portable.engine.export import load_weights
    import torch
    proof = read(ROOT / revision.REV / 'handoff.json')
    camp = ROOT / 'campaigns/a'
    head = read(camp / 'run/HEAD.json')
    store = CommitStore(camp / 'run', head['identity'])
    record = read(store.root / 'commits' / (proof['run_commit'] + '.json'))
    if digest(store.root / 'commits' / (proof['run_commit'] + '.json')) != proof['run_commit']:
        raise ValueError('handoff commit bytes changed')
    state = store.get_payload(record['payload'])
    if state_fingerprints(state) != proof['state_fingerprints'] or state['phase'] != 'COMMITTED' or state['cycle'] != 7:
        raise ValueError('exact committed c7 source missing')
    spec = read(camp / 'contract.json')
    export = camp / 'cycle-7-export/weights.json'
    if not export.exists():
        if export.parent.exists():
            raise ValueError('partial c7 export already exists; preserve')
        model = new_model(style_enabled=False, state_dict=state['model'])
        export.parent.mkdir()
        model.export(export, spec['run']['catalog_fingerprint'], provenance={
            'run_identity': head['identity'], 'commit': proof['run_commit'],
            'cycle': 7, 'sampling': 'softmax-t1', 'not_promoted': True})
    model = load_weights(export, expected_catalog_fingerprint=spec['run']['catalog_fingerprint'])
    for name, tensor in model.state_dict().items():
        if not torch.equal(tensor, state['model']['policy.' + name]):
            raise ValueError('recovered c7 tensor differs from original commit')
    ledger = CommitStore(camp / 'launch-ledger', spec['run']['arena_contract_sha256'])
    ledger_record = read(ledger.root / 'commits' / (proof['launch_ledger_commit'] + '.json'))
    ledger_state = ledger.get_payload(ledger_record['payload'])
    if len(ledger_state['attempts']) != 1792 or ledger_state['failed']:
        raise ValueError('retained complete ledger mismatch')
    summary_path = camp / 'cycle-7-summary.json'
    if not summary_path.exists():
        campaign = object.__new__(Campaign)
        campaign.root, campaign.spec = camp, spec
        campaign.run = SimpleNamespace(state=state, store=store)
        campaign._load = lambda: (proof['launch_ledger_commit'], ledger_state)
        summary = campaign.cycle_summary()
        summary.update(this_session_update_seconds=None,
            timing_status='NOT_MEASURED: original timer was interrupted after commit',
            restored_from_exact_commit=proof['run_commit'])
        write(summary_path, summary)
    if state_fingerprints(store.get_payload(record['payload'])) != proof['state_fingerprints']:
        raise ValueError('immutable source changed during read-only recovery')
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = dict(status='PASS_C7_ARTIFACTS_FROM_EXACT_COMMIT', new_games=0,
        new_optimizer_updates=0, source_commit=proof['run_commit'],
        source_fingerprints=proof['state_fingerprints'],
        exact_export_tensors=len(model.state_dict()), weights_sha256=digest(export),
        summary_sha256=digest(summary_path), adapter_sha256=digest(__file__),
        cpu_seconds=usage.ru_utime + usage.ru_stime,
        accounting_category='audit_transfer_control',
        accounting_status='EXTERNAL_RECEIPT_PENDING_FINAL_BUDGET_RECONCILIATION',
        observed_at=time.time())
    write(ROOT / revision.REV / 'c7-artifact-recovery.json', result)
    return result


if __name__ == '__main__':
    print(json.dumps(recover()), flush=True)
