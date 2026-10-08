"""Explicit M63 evaluation execution revision; frozen sources/receipts stay intact.

The original pipeline failed before dispatching any evaluation games. This
adapter reads the canonical M63 initialization field and delegates every raw
audit, match-grid, resource and statistical check to the frozen evaluator.
diagnose is read-only. prepare/run require a separately authorized execution
revision; importing this module never resumes training or evaluation.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_building_evaluation_m63 as frozen

REVISION = 'm63-evaluation-audit-schema-compat-r1'
CONFIG_SHA = 'c0d3de5398c724bd502d5c30f5f52ec06a848f7fe2672c28e1086c7730b21550'
CANONICAL = 'initial_36_tensors_and_rng_equal'
LEGACY = 'initial_policy_value_and_rng_equal'
ORIGINAL_AUDIT_EVIDENCE = frozen.audit_evidence


def canonical_binding(binding):
    frozen.require(binding.get('format') == 'm63-training-audit-binding-v1' and
                   binding.get('status') == 'PASS_TRAINING_ARTIFACT_AUDIT',
                   'R1 requires the canonical M63 PASS binding')
    frozen.require(binding.get(CANONICAL) is True and binding.get('completed_games') == 2048
                   and binding.get('groups') == 32, 'R1 canonical initialization/coverage incomplete')
    frozen.require(LEGACY not in binding or binding[LEGACY] is True,
                   'R1 conflicting legacy initialization flag')
    result = copy.deepcopy(binding)
    result[LEGACY] = True
    return result


def compatible_audit_evidence(project, pilot, audit, hashes, config_sha):
    return ORIGINAL_AUDIT_EVIDENCE(project, pilot, canonical_binding(audit), hashes, config_sha)


def preflight(project):
    project = Path(project).resolve()
    frozen.require(str(project) == frozen.CLOUD, 'R1 requires the original owned M63 root')
    failure_path = project / 'pipeline-driver-completion.json'
    failure = frozen.read(failure_path)
    frozen.require(failure.get('status') == 'FAILED_STOPPED_NO_RETRY'
                   and failure.get('config_sha256') == CONFIG_SHA
                   and failure.get('steps', {}).get('eval_prepare', {}).get('exit_code') == 1
                   and 'evaluation' not in failure.get('steps', {}),
                   'R1 requires preserved pre-dispatch failure')
    frozen.require('two-arm audit/initialization incomplete' in
                   failure['steps']['eval_prepare'].get('stderr', ''), 'R1 failure cause differs')
    frozen.audit_evidence = compatible_audit_evidence
    audit_path = project / 'training-artifact-audit.json'
    pilot, _, hashes = frozen.bindings(project, CONFIG_SHA, audit_path)
    for name, digest in pilot['runtime']['source_hashes'].items():
        frozen.require(frozen.sha(project / name) == digest, 'R1 frozen source drift: ' + name)
    frozen.descriptors(project, pilot, hashes)
    return dict(format=REVISION, original_failure_sha256=frozen.sha(failure_path),
                original_audit_sha256=frozen.sha(audit_path), config_sha256=CONFIG_SHA,
                candidate_sha256=hashes, adapter_sha256=frozen.sha(__file__),
                scope='canonical audit schema adapter; frozen grid, gates, weights and zero game retries',
                canonical_initialization_field=CANONICAL)


def verify_revision(project, execution):
    revision = preflight(project)
    frozen.require(execution.get('execution_revision') == revision, 'R1 execution revision drift')
    frozen.require(execution['files'].get(str(Path(__file__).resolve())) == frozen.sha(__file__),
                   'R1 adapter source is not pinned')
    frozen.verify(project / 'evaluation', execution)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('diagnose', 'prepare', 'verify', 'run'))
    parser.add_argument('--project', type=Path, default=Path(frozen.CLOUD))
    parser.add_argument('--execution-sha256')
    args = parser.parse_args()
    project = args.project.resolve()
    revision = preflight(project)
    if args.mode == 'diagnose':
        print(json.dumps(dict(status='PASS_READ_ONLY_COMPAT_PREFLIGHT', new_games=0, **revision)))
    elif args.mode == 'prepare':
        frozen.require(not (project / 'evaluation').exists(), 'R1 refuses existing evaluation')
        execution = frozen.prepare(project, CONFIG_SHA, project / 'training-artifact-audit.json')
        execution['execution_revision'] = revision
        execution['files'][str(Path(__file__).resolve())] = frozen.sha(__file__)
        verify_revision(project, execution)
        frozen.write(project / 'evaluation/execution.json', execution)
        print('R1 PREPARED_ZERO_GAMES: execution sha256=' + frozen.sha(project / 'evaluation/execution.json'))
    else:
        path = project / 'evaluation/execution.json'
        frozen.require(args.execution_sha256 and frozen.sha(path) == args.execution_sha256,
                       'R1 needs precommitted execution hash')
        verify_revision(project, frozen.read(path))
        if args.mode == 'run':
            frozen.run(project, args.execution_sha256)
        else:
            print('PASS_R1_EXECUTION_ZERO_GAMES')


if __name__ == '__main__':
    main()
