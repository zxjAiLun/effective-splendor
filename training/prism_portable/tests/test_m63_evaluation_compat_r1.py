"""Regression: accept the actual writer schema without weakening raw evidence checks."""
import copy
import pytest
from scripts import prism_m63_evaluation_compat_r1 as r1


def binding():
    return dict(format='m63-training-audit-binding-v1', status='PASS_TRAINING_ARTIFACT_AUDIT',
                initial_36_tensors_and_rng_equal=True, completed_games=2048, groups=32,
                arms={'control': {'candidate_sha256': 'a' * 64}, 'beta': {'candidate_sha256': 'b' * 64}})


def test_actual_writer_field_works_without_changing_frozen_receipt():
    raw = binding(); original = copy.deepcopy(raw)
    compatible = r1.canonical_binding(raw)
    assert compatible[r1.LEGACY] is True
    del compatible[r1.LEGACY]
    assert compatible == raw == original


@pytest.mark.parametrize('key,value', [
    (r1.CANONICAL, False), (r1.CANONICAL, 1), (r1.CANONICAL, None),
    ('completed_games', 2047), ('groups', 31), ('status', 'RUNNING'),
    ('format', 'm62-training-audit-binding-v1'), (r1.LEGACY, False),
])
def test_rejects_incomplete_or_conflicting_audit(key, value):
    raw = binding(); raw[key] = value
    with pytest.raises(ValueError):
        r1.canonical_binding(raw)


def test_legacy_only_cannot_substitute_for_canonical_initialization():
    raw = binding(); del raw[r1.CANONICAL]; raw[r1.LEGACY] = True
    with pytest.raises(ValueError):
        r1.canonical_binding(raw)


def test_delegates_raw_validation_and_preserves_rejection(monkeypatch):
    def checker(project, pilot, audit, hashes, config_sha):
        assert audit[r1.CANONICAL] is audit[r1.LEGACY] is True
        assert hashes == {'beta': 'changed-weight'}
        raise ValueError('raw audit weight drift')
    monkeypatch.setattr(r1, 'ORIGINAL_AUDIT_EVIDENCE', checker)
    with pytest.raises(ValueError, match='raw audit weight drift'):
        r1.compatible_audit_evidence(None, None, binding(), {'beta': 'changed-weight'}, 'config')
