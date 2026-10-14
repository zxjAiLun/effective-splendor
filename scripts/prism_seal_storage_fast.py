"""Execution-only, byte-compatible serialization for the M81 r5 adapter.

SealScope is confined to the synchronous, pinned Run.seal implementation: its
inputs are freshly hash-checked shards, and that implementation never mutates
input feature arrays. No cache survives the seal or is used during inference.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import pickle
from types import SimpleNamespace


class PrimitivePickler(pickle.Pickler):
    def reducer_override(self, obj):
        raise TypeError('ledger must contain only builtin primitive containers')


class PrimitivePicklerFactory:
    def __new__(cls, *args, **kwargs):
        # torch derives its persistent_id pickler from this factory. Returning
        # the initialized C pickler avoids a Python tensor probe for every
        # primitive in a ledger which contains no tensors. Nonprimitive objects
        # are rejected rather than silently serialized without tensor handling.
        return PrimitivePickler(*args, **kwargs)


def ledger_payload_bytes(payload):
    import torch
    stream = io.BytesIO()
    module = SimpleNamespace(__name__='pickle', Pickler=PrimitivePicklerFactory)
    torch.save(payload, stream, pickle_module=module)
    return stream.getvalue()


def install_ledger_serializer():
    from training.prism_portable.engine.ppo.store import CommitStore
    original = CommitStore.put_payload
    def put_payload(self, payload):
        if self.root.name != 'launch-ledger':
            return original(self, payload)
        return self._put('objects', ledger_payload_bytes(payload), '.pt')
    CommitStore.put_payload = put_payload


class SealScope:
    def __init__(self):
        self.inputs = {}
        self.checked = {}
        self.metrics = dict(input_validations=0, input_validation_reuses=0,
                            input_encodings=0, input_encoding_reuses=0)

    @staticmethod
    def plain(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

    def encoded_input(self, value):
        key = id(value)
        entry = self.inputs.get(key)
        if entry is None:
            entry = (value, self.plain(value))
            self.inputs[key] = entry
            self.metrics['input_encodings'] += 1
        else:
            assert entry[0] is value
            self.metrics['input_encoding_reuses'] += 1
        return entry[1]

    def object(self, value, special):
        return '{' + ','.join(self.plain(k) + ':' +
                             (special[k](v) if k in special else self.plain(v))
                             for k, v in sorted(value.items())) + '}'

    def array(self, values, encode):
        return '[' + ','.join(encode(value) for value in values) + ']'

    def game(self, value):
        def decision(row):
            return self.object(row, {'request': lambda request:
                                    self.object(request, {'input': self.encoded_input})})
        return self.object(value, {'decisions': lambda rows: self.array(rows, decision)})

    def encode(self, value):
        if isinstance(value, dict) and value.get('format') == 'prism-ppo-batch-v1':
            return self.object(value, {'rows': lambda rows: self.array(rows, lambda row:
                               self.object(row, {'input': self.encoded_input}))})
        if isinstance(value, list) and value and all(isinstance(v, dict) and
                v.get('format') == 'prism-ppo-game-v1' for v in value):
            return self.array(value, self.game)
        return self.plain(value)

    @contextmanager
    def installed(self):
        from training.prism_portable.engine.ppo import contract, learner, store
        old_validate, old_hash, old_bytes = contract.validate_input, learner.canonical_hash, store.json_bytes
        def validate(value):
            key = id(value)
            if key not in self.checked:
                result = old_validate(value)
                self.checked[key] = value
                self.metrics['input_validations'] += 1
                return result
            assert self.checked[key] is value
            self.metrics['input_validation_reuses'] += 1
            return value
        contract.validate_input = validate
        learner.canonical_hash = lambda value: hashlib.sha256(self.encode(value).encode('utf-8')).hexdigest()
        store.json_bytes = lambda value: (self.encode(value) + '\n').encode('utf-8')
        try:
            yield self
        finally:
            contract.validate_input, learner.canonical_hash, store.json_bytes = old_validate, old_hash, old_bytes
            self.inputs.clear()
            self.checked.clear()
