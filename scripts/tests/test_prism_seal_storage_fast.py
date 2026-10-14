import copy
import io
import json
import math
import random

import pytest
import torch

from scripts.prism_seal_storage_fast import SealScope, ledger_payload_bytes


def test_ledger_torch_bytes_and_reload_exact():
    shared = {'status': 'COMPLETE', 'job': {'actor': 0, 'job_id': '例"\\\n'}}
    data = {'attempts': {str(i): dict(shared, decisions=i) for i in range(500)},
            'reused': [shared, shared], 'failed': False, 'none': None,
            'number': [2**63, -0.0, 0.12345678901234567]}
    original = io.BytesIO(); torch.save(data, original)
    fast = ledger_payload_bytes(data)
    assert fast == original.getvalue()
    restored = torch.load(io.BytesIO(fast), weights_only=False)
    assert restored == data
    assert restored['reused'][0] is restored['reused'][1]


def test_ledger_rejects_tensor_and_other_nonprimitive():
    with pytest.raises(TypeError): ledger_payload_bytes({'bad': torch.zeros(2)})
    with pytest.raises(TypeError): ledger_payload_bytes({'bad': {1, 2}})


def fixture():
    r = random.Random(34)
    return {'entities': [[r.uniform(-1, 1) for _ in range(96)]],
            'actions': [[0.] * 80], 'targets': [-1]}


def test_canonical_fragments_exact_in_games_batch_and_store():
    feature = fixture()
    games = [{'format': 'prism-ppo-game-v1', 'job_id': '中\\"\n',
              'decisions': [{'request': {'input': feature, 'actor': 0}, 'response': {'value': .5}}]}]
    batch = {'format': 'prism-ppo-batch-v1', 'rows': [{'input': feature, 'advantage': -0.0}],
             'other': [1, None, True, 1e-100, 1e100]}
    cache = SealScope()
    for value in (games, batch, dict(batch, batch_id='abc'), batch):
        assert cache.encode(value) == json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert cache.metrics['input_encodings'] == 1
    assert cache.metrics['input_encoding_reuses'] == 3
    changed = copy.deepcopy(batch); changed['rows'][0]['input']['actions'][0][0] = 7.
    assert cache.encode(changed) == cache.plain(changed)


def test_scope_restores_on_error_and_revalidates_next_scope():
    from training.prism_portable.engine.ppo import contract, learner, store
    originals = contract.validate_input, learner.canonical_hash, store.json_bytes
    feature = fixture(); scope = SealScope()
    with pytest.raises(RuntimeError):
        with scope.installed():
            contract.validate_input(feature); contract.validate_input(feature)
            assert scope.metrics['input_validations'] == 1
            assert scope.metrics['input_validation_reuses'] == 1
            raise RuntimeError('fault')
    assert originals == (contract.validate_input, learner.canonical_hash, store.json_bytes)
    assert not scope.inputs and not scope.checked
    feature['actions'][0][0] = True
    with SealScope().installed(), pytest.raises(ValueError): contract.validate_input(feature)


@pytest.mark.parametrize('bad', [True, float('nan'), float('inf')])
def test_first_input_validation_still_rejects_bad_features(bad):
    from training.prism_portable.engine.ppo import contract
    value = fixture(); value['entities'][0][0] = bad
    with SealScope().installed(), pytest.raises(ValueError): contract.validate_input(value)
