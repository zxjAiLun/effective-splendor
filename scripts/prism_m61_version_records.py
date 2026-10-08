"""Register explicit M61 experimental identities after a pinned re-audit receipt.

No training, games, remote access or deployment. Original M61 bytes remain fixed.
All evidence and destination collisions are checked before writing any output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REVISION = 'M61 re-audit-r1'
WORK = 'local-artifacts/prism/balance-ab-m61'
ORIGINAL_HASHES = {
    'benchmarks/m61-prism-alpha-balance-ab.config.json': '280efde1a7441e82d072f33f22b97c24b2d1f5653de76ccfeecb72729ac53fd9',
    'benchmarks/m61-prism-alpha-ab.train.json': '6e82d362b9b17a603f6132780bd8b5bcb9aa3f7ced93f3214ab668a3fd9508f4',
    'benchmarks/m61-prism-balance-ab.train.json': '0e62f8a0e8f4736a2574e0f8e73ce616b8b4f957f6a7ef5c89cf6a253784cd6e',
    WORK + '/result.json': '37834fd4571503b269924f6ab62d9dd423a6b7d8e317f75a8930c1d96c46c6a4',
    WORK + '/execution.json': 'ba117541dce0350f83f0123b8f85b3388d17e5f9b85040cf314812595651171c',
    WORK + '/completion.json': 'ee03299410e11994d060bfbff1382ef069e0447d01518ba9e2c56d8d73b89fb3',
    WORK + '/training-artifact-audit.json': '997aff9be74d7604cd60bc85cceccc891a760ab9fbbe3fede6903f52f71e81bf',
    'docs/prism/m61-prism-alpha-balance-ab-evaluation.md': 'f4033572bae221ced35b8e4d403290c4f5cd1e6b2f2bbecff09bb1c79ab171a3',
    'scripts/prism_balance_ab_audit_m61.py': '0c9897cb412aa7c56b35f1f8ee769cc5d3ab5899f0fde38cf644f019a49735c7',
    'scripts/prism_balance_ab_prepare_m61.py': 'c352c7566a5d2bda90ea7065ab248056d613786a9ed1f9f1758adcd089869ee6',
    'scripts/prism_balance_ab_evaluation_m61.py': 'd7ff23e9aec80352005b296caa6f79b0dfec5ab0e9867d910ea260cad65bbde9',
    'scripts/prism_balance_ab_report_m61.py': '118e4b03291906659607b6698d37d8dd7dac1ac74b1bbee27cde7c9db907ce05',
    'scripts/prism_balance_ab_training_report_m61.py': '7bb460bdd236658fa4f8babd0874233d35f14033754a2a11dfd02d438bb2a434',
    'local-artifacts/prism/alpha-v0.1.3/weights.json': '7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544',
    'local-artifacts/prism/alpha-v0.1.3/weights.manifest.json': '52da0740c4badb397f59d40b09716ba4c5ff860061b86322a32c32a3af478335',
    'local-artifacts/prism/v0.1.1/weights.json': 'a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85',
}
PARENT_SHA = '7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544'
CANDIDATE_SHAS = {
    'alpha': 'd3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9',
    'balance': '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1',
}
VERSIONS = {'alpha': '0.1.4', 'balance': '0.1.0'}
NAMES = {'alpha': 'Prism Alpha v0.1.4', 'balance': 'Prism Balance v0.1.0'}
OLD_LABELS = {
    'Alpha 续训（M61 未发布最终 c4，原 style）': NAMES['alpha'] + '（原 style，实验版）',
    'Balance（M61 未发布最终 c4，outcome-only）': NAMES['balance'] + '（outcome-only，实验版）',
    'Alpha 续训（M61 未发布最终 c4，T=1）': NAMES['alpha'] + '（T=1，实验版）',
    'Balance（M61 未发布最终 c4，T=1）': NAMES['balance'] + '（T=1，实验版）',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def relative(root, path):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError as exc:
        raise ValueError('evidence must be archived inside project: ' + str(path)) from exc


def local_path(root, value):
    path = Path(value)
    path = path if path.is_absolute() else Path(root) / path
    relative(root, path)
    require(path.is_file(), 'missing local evidence: ' + str(path))
    return path


def descriptor(root, path):
    return {'path': relative(root, path), 'sha256': sha(path)}


def checked_descriptor(root, item, label):
    require(isinstance(item, dict) and set(('path', 'sha256')) <= set(item),
            'missing hash-bound ' + label)
    path = local_path(root, item['path'])
    require(sha(path) == item['sha256'], label + ' drift: ' + str(path))
    return path


def frozen_inputs(root):
    root = Path(root)
    for name, digest in ORIGINAL_HASHES.items():
        path = local_path(root, name)
        require(sha(path) == digest, 'frozen original input drift: ' + name)
    config = read(root / 'benchmarks/m61-prism-alpha-balance-ab.config.json')
    result = read(root / WORK / 'result.json')
    execution = read(root / WORK / 'execution.json')
    completion = read(root / WORK / 'completion.json')
    require(result['format'] == 'm61-balance-ab-evaluation-result-v1' and
            result['status'] == 'COMPLETED_FIXED_AB_EVALUATION', 'original evaluation incomplete')
    require(result['candidate_sha256'] == execution['candidate_sha256'] == CANDIDATE_SHAS,
            'original candidate identity drift')
    require(result['config_sha256'] == execution['config_sha256'] ==
            ORIGINAL_HASHES['benchmarks/m61-prism-alpha-balance-ab.config.json'], 'config binding drift')
    require(result['execution_sha256'] == ORIGINAL_HASHES[WORK + '/execution.json'],
            'execution binding drift')
    require(completion['result_sha256'] == ORIGINAL_HASHES[WORK + '/result.json'] and
            completion['physical_games'] == 8256 and completion['retry'] == 0 and
            completion['formal_gates_analyzed_once'] is True, 'original completion binding drift')
    require(result['development']['games'] == 576 and result['acceptance']['games'] == 7680,
            'development/independent coverage drift')
    require(result['acceptance_policy'] == config['evaluation']['acceptance'] ==
            execution['evaluation']['acceptance'], 'frozen policy drift')
    require(config['base_model']['sha256'] == execution['candidates']['base']['sha256'] == PARENT_SHA,
            'parent identity drift')
    from scripts.prism_balance_ab_report_m61 import validate_measurements
    validate_measurements(result)
    require(all(result['gates'].values()) and result['arm_verdicts'] ==
            {'alpha': 'PASS_RETENTION_FLOORS', 'balance': 'PASS_RETENTION_FLOORS'},
            'identity requires original retention floors')
    require(result['comparison']['verdict'] == 'INCONCLUSIVE' and
            result['balance_style_acceptance'] == 'NOT_CLAIMED', 'original verdict drift')
    return config, result, execution


def validate_reaudit(root, receipt_path, result, fetch_receipt_path):
    """Verify immutable remote completion and its independently bound local archive.

    Raw input and runtime-library inventories were checked on the execution host.
    Locally, every archived source, candidate and fetched output is hash checked.
    Unfetched raw input paths remain explicit; no local full-replay audit is claimed.
    """
    receipt_path = local_path(root, receipt_path)
    receipt = read(receipt_path)
    require(receipt.get('format') == 'm61-reaudit-r1-execution-receipt-v1' and
            receipt.get('status') == 'PASS_M61_REAUDIT_R1', 'registration requires real re-audit-r1 PASS')
    require(receipt.get('exit_code') == 0 and receipt.get('failures') == [] and
            receipt.get('new_games') == 0 and receipt.get('new_optimizer_updates') == 0 and
            receipt.get('retries') == 0 and receipt.get('old_receipts_preserved') is True,
            're-audit unsuccessful execution, failures or new work')
    fetch_path = local_path(root, fetch_receipt_path)
    fetch = read(fetch_path)
    require(fetch.get('format') == 'm61-reaudit-r1-local-fetch-receipt-v1' and
            fetch.get('status') == 'PASS_FETCH_HASH_VERIFICATION', 'verified local fetch receipt required')
    require(checked_descriptor(root, fetch['completion'], 'fetched completion').resolve() == receipt_path.resolve(),
            'fetch completion path mismatch')
    execution_path = checked_descriptor(root, fetch['execution'], 're-audit execution')
    require(sha(execution_path) == receipt.get('execution_sha256') and
            fetch['execution']['remote_path'] == receipt.get('execution_path'),
            're-audit execution receipt drift')
    executed = read(execution_path)
    require(executed.get('format') == 'm61-reaudit-r1-execution-v1' and
            executed.get('revision') == REVISION, 'explicit executed revision missing or wrong')
    require(isinstance(executed.get('argv'), list) and executed['argv'] == receipt.get('argv') and
            any(str(arg).endswith('prism_balance_ab_reaudit_m61.py') for arg in executed['argv']),
            'execution argv is not the pinned re-audit revision')
    require(all(executed.get(key) == 0 for key in ('new_games', 'new_optimizer_updates', 'retries')),
            're-audit start contract allowed new work')
    require(receipt.get('ended_at', 0) >= receipt.get('started_at', 1) == executed.get('started_at') and
            receipt.get('wall_seconds', -1) >= 0, 're-audit execution clock missing')
    pins = receipt.get('source_pins')
    require(isinstance(pins, dict) and pins and executed.get('source_pins') == pins,
            'executed source manifest missing or unbound')
    require(isinstance(receipt.get('runtime_pins'), dict) and receipt['runtime_pins'] and
            all(receipt['runtime_pins'].get(path) == digest for path, digest in executed.get('runtime_pins', {}).items()),
            'runtime pin inventory drift')
    require(isinstance(receipt.get('inputs'), dict) and receipt['inputs'] and
            all(receipt['inputs'].get(path) == digest for path, digest in executed.get('inputs', {}).items()),
            'executed input inventory drift')
    require(isinstance(receipt.get('outputs'), dict) and receipt['outputs'], 'output inventory missing')
    maps, map_paths = {}, {}
    for kind in ('source', 'artifact'):
        path = checked_descriptor(root, fetch[kind + '_map'], kind + ' archive map')
        value = read(path)
        require(value.get('format') == 'm61-reaudit-r1-local-map-v1' and isinstance(value.get('rows'), list),
                'wrong local archive map format')
        rows = {}
        for row in value['rows']:
            remote = row['remote_path']
            require(remote not in rows, 'duplicate remote archive mapping: ' + remote)
            local = checked_descriptor(root, {'path': row['local_path'], 'sha256': row['sha256']},
                                       kind + ' archived bytes')
            rows[remote] = {**row, 'path': relative(root, local)}
        maps[kind], map_paths[kind] = rows, descriptor(root, path)
    source_rows = maps['source']
    require(set(pins) <= set(source_rows), 'executed source archive incomplete')
    for remote, digest in pins.items():
        require(source_rows[remote]['sha256'] == digest, 'archived source pin drift: ' + remote)
    config = read(Path(root) / 'benchmarks/m61-prism-alpha-balance-ab.config.json')
    require(isinstance(executed.get('cwd'), str) and executed['cwd'], 'executed source root missing')
    for name, digest in config['runtime']['source_hashes'].items():
        remote = executed['cwd'].rstrip('/') + '/' + name
        require(pins.get(remote) == digest, 'frozen M61 source omitted or changed: ' + name)
    revision = executed.get('revision_script', {})
    require(revision.get('path') in pins and pins[revision['path']] == revision.get('sha256') and
            revision['path'] in executed['argv'], 'revision script/argv/source pin mismatch')
    require(any('test_m61' in remote for remote in pins), 're-audit test source not pinned')
    artifacts = maps['artifact']
    inventories = {**receipt['inputs'], **receipt['outputs']}
    for remote, row in artifacts.items():
        require(inventories.get(remote) == row['sha256'], 'archived artifact pin drift: ' + remote)
    unfetched = fetch.get('unfetched_inputs')
    require(isinstance(unfetched, list) and len(unfetched) == len(set(unfetched)) and
            set(unfetched) == set(receipt['inputs']) - set(artifacts) - set(source_rows),
            'unfetched raw input inventory incomplete or misleading')

    def mapped(remote, digest, label):
        require(remote in artifacts and artifacts[remote]['sha256'] == digest,
                label + ' missing or drifted artifact archive')
        return local_path(root, artifacts[remote]['local_path'])

    candidates = {}
    require(set(receipt.get('arms', {})) == set(fetch.get('candidates', {})) == {'alpha', 'balance'},
            're-audit arm coverage drift')
    for arm, row in receipt['arms'].items():
        require(row.get('status') == 'PASS_TRAINING_ARTIFACT_AUDIT' and row.get('games') == 1024 and
                row.get('candidate_sha256') == result['candidate_sha256'][arm] == CANDIDATE_SHAS[arm],
                're-audit arm/candidate identity drift: ' + arm)
        downloaded = fetch['candidates'][arm]
        weights = mapped(row['candidate_path'], row['candidate_sha256'], arm + ' candidate')
        companion = mapped(row['manifest_path'], row['manifest_sha256'], arm + ' companion')
        for key, source, remote in (('weights', weights, row['candidate_path']),
                                    ('manifest', companion, row['manifest_path'])):
            require(checked_descriptor(root, downloaded[key], arm + ' fetched ' + key).resolve() == source.resolve() and
                    downloaded[key]['remote_path'] == remote, 'fetched candidate source drift')
        require(receipt['inputs'].get(row['candidate_path']) == CANDIDATE_SHAS[arm] and
                receipt['inputs'].get(row['manifest_path']) == row['manifest_sha256'],
                'candidate not pinned in executed input inventory')
        outputs = {}
        for key in ('checkpoint_validation', 'final_parity', 'training_audit', 'source_ledger', 'comparison'):
            ref = row[key]
            require(receipt['outputs'].get(ref['path']) == ref['sha256'], 'arm output not bound: ' + key)
            path = mapped(ref['path'], ref['sha256'], arm + ' ' + key)
            value = read(path)
            outputs[key] = descriptor(root, path)
            if key != 'source_ledger':
                expected_status = ('PASS_EXACT_CONTENT_PARITY' if key == 'comparison' else
                                   'PASS_TRAINING_ARTIFACT_AUDIT' if key == 'training_audit' else 'PASS')
                require(value.get('status') == expected_status, 're-audit arm receipt not PASS: ' + key)
                if key != 'comparison':
                    zero_key = 'new_matches' if key == 'training_audit' else 'new_games'
                    require(value.get(zero_key) == 0 and value.get('new_optimizer_updates') == 0,
                            'arm receipt records new work: ' + key)
        checkpoint = read(local_path(root, outputs['checkpoint_validation']['path']))
        require(checkpoint.get('final_weights_sha256') == CANDIDATE_SHAS[arm] and
                checkpoint.get('parent_sha256') == PARENT_SHA and checkpoint.get('exact_export_tensors') == 32,
                'checkpoint identity/tensor evidence drift')
        manifest = read(companion)
        require(manifest.get('format') == 'prism-weights-manifest-v1' and
                manifest.get('weights_sha256') == CANDIDATE_SHAS[arm] and
                manifest.get('provenance', {}).get('cycle') == 4 and
                manifest['provenance'].get('run_identity') == checkpoint.get('run_identity'),
                'candidate companion provenance drift')
        parity = read(local_path(root, outputs['final_parity']['path']))
        require(parity.get('weights_sha256') == CANDIDATE_SHAS[arm] and
                parity.get('boundary_inputs') == 68 and parity.get('atol') == 1e-4 and
                parity.get('rtol') == 1e-4 and parity.get('native_exit_code') == 0,
                're-audit combined-tolerance parity contract drift')
        require(row.get('parity_max_abs_error') == parity['max_abs_error'], 'parity receipt summary drift')
        candidates[arm] = {'weights': descriptor(root, weights), 'companion': descriptor(root, companion),
                           'audit_outputs': outputs}
    from datetime import datetime, timezone
    completed_at = datetime.fromtimestamp(receipt['ended_at'], timezone.utc).isoformat()
    return {'revision': REVISION, 'status': receipt['status'], 'completed_at': completed_at,
            'completion': descriptor(root, receipt_path), 'execution_receipt': descriptor(root, execution_path),
            'source_manifest': map_paths['source'], 'artifact_manifest': map_paths['artifact'],
            'fetch_receipt': descriptor(root, fetch_path), 'source_pins': pins,
            'runtime_pins': receipt['runtime_pins'], 'unfetched_inputs': unfetched,
            'candidates': candidates, 'original_failures_preserved': True,
            'source_scope': 'executed M61 revision and archived source pins; not current engine identity',
            'raw_input_scope': 'full remote re-audit; local verification of fetched evidence only'}


def table(headers, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')
    return '\n'.join(['| ' + ' | '.join(map(cell, headers)) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows])


def remapped_report(original):
    """Map display labels only; preserve every table and original provenance label."""
    start = original.index('## 同种子共同锚点：')
    boundary = original.index('## 冻结执行合同、模型与运行身份')
    display, provenance = original[start:boundary], original[boundary:]
    for old, new in OLD_LABELS.items():
        display = display.replace(old, new)
    # Statistical keys alpha/balance remain frozen experiment identifiers.
    return display + '\n## 冻结原始来源（历史字面标签保留）\n\n' + (
        '以下来源表、字面运行命令及原结论按原报告保留；其中“未发布最终c4”、'
        '“不自动注册”等措辞属于原收官时点。当前实验身份以上方登记记录为准，'
        '原竞技判定、阈值、失败记录和源SHA不变。\n\n') + provenance


def render_summary(arm, root, result, reaudit):
    name = NAMES[arm]
    artifact = 'local-artifacts/prism/' + arm + '-v' + VERSIONS[arm]
    report_path = Path(root) / 'docs/prism/m61-prism-alpha-balance-ab-evaluation.md'
    if arm == 'alpha':
        competitive = ('原三项保留门 **PASS_RETENTION_FLOORS**，接受为 Prism Alpha v0.1.3 '
                       '的大牌取分实验后继。共同锚点半平得分率变化 **↑ +2.0833个百分点**，'
                       '七项同时CI **[-1.6789,+5.8268]个百分点**；总体增强未确认。'
                       '直接对父模型52.9785%，同时CI [48.7793%,57.0593%]，未确认直接优势。')
        style = ('大牌印刷VP AUC24变化 **↑ +0.006612**，七项同时CI '
                 '**[+0.002680,+0.010522]**；该指标相对 Prism Alpha v0.1.3 增强有证据。'
                 '原风格保留门为下界≥−0.015，不改成新的增强门。')
        decision = 'ACCEPTED_BIGCARD_CONTINUATION；原M61三项保留门PASS的实验后继'
    else:
        competitive = ('原两项棋力保留门 **PASS_RETENTION_FLOORS**。共同锚点半平得分率变化 '
                       '**↑ +0.5534个百分点**，七项同时CI **[-3.1576,+4.3945]个百分点**；'
                       '总体增强未确认。直接对父模型53.0273%，同时CI [48.8770%,57.1082%]，'
                       '未确认直接优势。Prism Balance v0.1.0 是从 Prism Alpha v0.1.3 '
                       '分出的新实验谱系；通用 Prism v0.1.1 身份保持固定。')
        style = ('outcome-only、style_beta=0、style_value_weight=0 是训练处理。'
                 '原 `balance_style_acceptance: NOT_CLAIMED` 保留，不能据此验收均衡、基建或干扰风格。'
                 '折扣、贵族、大牌与预留变化属于描述指标。')
        decision = 'REGISTERED_EXPERIMENTAL_MODEL；新Balance谱系，两项原棋力保留门PASS'
    rows = [
        ('名称 / ID', name + ' / prism-' + arm + '-v' + VERSIONS[arm]),
        ('身份状态', 'REGISTERED_EXPERIMENTAL_MODEL；' + decision),
        ('直接父模型', 'Prism Alpha v0.1.3 / prism-alpha-v0.1.3 / ' + PARENT_SHA),
        ('原候选权重SHA256', CANDIDATE_SHAS[arm]),
        ('不可变归档', artifact + '/weights.json；weights.manifest.json'),
        ('运行动作模式', 'agent-prism-sample；softmax T=1；动作RNG 61032001（原result/config）'),
        ('登记范围', '固定实验身份；0新局、0新优化；默认/共享池/Studio未部署'),
        ('原报告SHA256', ORIGINAL_HASHES['docs/prism/m61-prism-alpha-balance-ab-evaluation.md']),
        ('新只读审计修订', REVISION),
        ('新审计completion', reaudit['completion']['path'] + ' / ' + reaudit['completion']['sha256']),
        ('新审计source manifest', reaudit['source_manifest']['path'] + ' / ' + reaudit['source_manifest']['sha256']),
        ('新审计执行receipt', reaudit['execution_receipt']['path'] + ' / ' + reaudit['execution_receipt']['sha256']),
    ]
    original = report_path.read_text(encoding='utf-8')
    out = [
        '# ' + name + '：固定实验身份与完整对战记录',
        '**产物：**与M61 ' + arm + ' 最终c4同一份权重。真实 **' + REVISION + '** '
        '已按绑定执行修订通过只读产物复核，身份状态 **REGISTERED_EXPERIMENTAL_MODEL**。'
        '源manifest与执行receipt均绑定在本页和模型JSON；本次登记未追加训练或比赛。',
        '**竞技：**' + competitive,
        '**风格：**' + style,
        'A/B原判定仍为 **INCONCLUSIVE**。Balance对Alpha半平得分率50.2441%，七项同时CI '
        '[46.1426%,54.4922%]；共同锚点Balance−Alpha变化−1.5299个百分点，CI '
        '[−5.2083,+2.2135]个百分点。未确认任一方向，不证明等效；登记不宣称普适更强或等强。',
        '## 版本身份与只读审计来源', table(['字段', '固定记录'], rows),
        '## 审计来源更正与边界',
        '原冻结训练报告命令曾以 `KeyError: game_id` 退出1；随后临时字段适配补丁没有持久化或'
        '执行源码绑定。该失败、旧PASS receipts及原训练绑定SHA全部保留。新 '
        + REVISION + ' 是另立执行修订，补齐原始产物审计来源，不重训、不重开竞技验收。',
        'Parity使用 `math.isclose(rel_tol=1e-4, abs_tol=1e-4)` 的绝对与相对组合容差；'
        '判据为误差≤max(1e-4,1e-4×max(|a|,|b|))。原68边界receipt最大绝对误差'
        'Alpha为0.0001527441406210528、Balance为0.0001047607421895691；'
        '不能写成两者绝对误差均小于1e-4。新复核值见绑定产物receipt。',
        '原竞技数据共8,256局：开发576局仅描述，独立验收7,680局。没有双盲执行证明。'
        '原七项20,000次配对双座seed-block bootstrap、阈值、CI和判定原样引用，不重算统计。'
        '当前工作树可包含后续engine变更；M61运行身份由当时冻结二进制及归档源码manifest绑定，'
        '不声称当前engine与M61运行时逐字节相同。',
        '## 人类显示名映射与原判保留',
        table(['原冻结显示名', '当前显示名'], OLD_LABELS.items()),
        '下方完整双方表沿用同一场比赛，以当前完整版本名显示。模型本人指标、对手本人指标和'
        '整局指标的归属保持；先手P0和后手P1仍按模型身份聚合。箭头只表示方向，'
        '不代表更好或统计显著。原json键、命令、路径与历史候选名称在来源区按字面保留。',
        remapped_report(original),
    ]
    return '\n\n'.join(out).rstrip() + '\n'


def build_record(arm, root, config, result, execution, reaudit, report_bytes):
    model_id = 'prism-' + arm + '-v' + VERSIONS[arm]
    artifact = 'local-artifacts/prism/' + arm + '-v' + VERSIONS[arm]
    candidate = reaudit['candidates'][arm]
    return {
        'format': 'prism-experimental-model-identity-v1',
        'status': 'REGISTERED_EXPERIMENTAL_MODEL', 'identity_status': 'REGISTERED_EXPERIMENTAL_MODEL',
        'display_name': NAMES[arm], 'model_id': model_id, 'model_version': VERSIONS[arm],
        'frozen_at': reaudit['completed_at'],
        'weights_path': artifact + '/weights.json', 'weights_sha256': CANDIDATE_SHAS[arm],
        'companion_path': artifact + '/weights.manifest.json',
        'companion_sha256': candidate['companion']['sha256'],
        'parent': {'display_name': 'Prism Alpha v0.1.3', 'model_id': 'prism-alpha-v0.1.3',
                   'weights_path': 'local-artifacts/prism/alpha-v0.1.3/weights.json', 'sha256': PARENT_SHA},
        'origin': {'milestone': 'M61', 'arm': arm, 'cycle': 4, 'source_weights': candidate['weights'],
                   'source_companion': candidate['companion'],
                   'original_candidate_descriptor': execution['candidates'][arm],
                   'training_games': 1024, 'training_updates': 216,
                   'style_beta': config['training']['arms'][arm]['ppo']['style_beta'],
                   'style_value_weight': config['training']['arms'][arm]['ppo']['style_value_weight']},
        'lineage': {'kind': 'Alpha accepted retention experimental successor' if arm == 'alpha'
                    else 'Balance new outcome-only experimental branch from Alpha',
                    'generic_prism_v0.1.1_unchanged': True},
        'runtime': {'action_mode': 'softmax-t1', 'temperature': 1.0, 'action_seed': 61032001,
                    'source': 'original M61 result.acceptance_policy and frozen execution.evaluation',
                    'engine': execution['binaries']['engine'], 'no_inference_overlay': True},
        'independent_acceptance': {
            'status': 'ACCEPTED_BIGCARD_CONTINUATION' if arm == 'alpha' else 'PASS_RETENTION_FLOORS',
            'original_arm_verdict': result['arm_verdicts'][arm],
            'gates': {key.split('/', 1)[1]: passed for key, passed in result['gates'].items()
                      if key.startswith(arm + '/')},
            'measurements': {key: value for key, value in result['measurements'].items()
                             if key.startswith(arm + '/')},
            'development_games_cohort': 576, 'independent_games_cohort': 7680,
            'original_result': descriptor(root, Path(root) / WORK / 'result.json'),
            'statistics_recomputed': False,
        },
        'comparison': result['comparison'],
        'confirmed_enhancement': {'bigcard_auc24': arm == 'alpha', 'direct_parent': False,
                                  'overall_anchor_strength': False},
        'style_descriptor': '大牌取分 / 大牌冲分取向' if arm == 'alpha'
                            else 'outcome-only；继承Alpha策略；未验收均衡风格',
        'balance_style_acceptance': result['balance_style_acceptance'],
        'reaudit': {key: value for key, value in reaudit.items() if key != 'candidates'},
        'original_evidence': dict(ORIGINAL_HASHES),
        'historical_names': [execution['candidates'][arm]['display_name'],
                             *[old for old in OLD_LABELS if old.startswith('Alpha' if arm == 'alpha' else 'Balance')]],
        'readable_report': 'docs/prism/' + model_id + '-evaluation-summary.md',
        'readable_report_sha256': hashlib.sha256(report_bytes).hexdigest(),
        'registrar': descriptor(root, Path(root) / 'scripts/prism_m61_version_records.py'),
        'default_replaced': False, 'shared_pool_deployed': False, 'studio_deployed': False,
        'git_published': False, 'identity_registration_games': 0,
        'identity_registration_training_updates': 0,
    }


def output_plan(root, receipt_path, fetch_receipt_path):
    """Read-only preflight; returns all destination bytes only after real receipt PASS."""
    root = Path(root)
    config, result, execution = frozen_inputs(root)
    reaudit = validate_reaudit(root, receipt_path, result, fetch_receipt_path)
    outputs = {}
    for arm in ('alpha', 'balance'):
        candidate = reaudit['candidates'][arm]
        folder = root / 'local-artifacts/prism' / (arm + '-v' + VERSIONS[arm])
        for key, filename in (('weights', 'weights.json'), ('companion', 'weights.manifest.json')):
            source = checked_descriptor(root, candidate[key], arm + ' ' + key)
            outputs[folder / filename] = source.read_bytes()
        report = render_summary(arm, root, result, reaudit).encode('utf-8')
        outputs[root / 'docs/prism' / ('prism-' + arm + '-v' + VERSIONS[arm] + '-evaluation-summary.md')] = report
        record = build_record(arm, root, config, result, execution, reaudit, report)
        outputs[root / 'benchmarks' / ('m61-prism-' + arm + '-v' + VERSIONS[arm] + '.model.json')] = (
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    for dest, data in outputs.items():
        require(not dest.is_symlink(), 'immutable identity destination is a symlink: ' + str(dest))
        if dest.exists():
            require(dest.is_file() and dest.read_bytes() == data,
                    'immutable identity collision: ' + str(dest))
    return outputs


def register(root, receipt_path, fetch_receipt_path, check_only=False):
    outputs = output_plan(root, receipt_path, fetch_receipt_path)
    if not check_only:
        for dest, data in outputs.items():
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create prevents silent overwrite even after the preflight.
            with dest.open('xb') as stream:
                stream.write(data)
    return {relative(root, path): hashlib.sha256(data).hexdigest() for path, data in outputs.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--reaudit', type=Path, required=True,
                        help='real M61 re-audit-r1 completion receipt (local archived path)')
    parser.add_argument('--fetch-receipt', type=Path, required=True,
                        help='hash-bound local fetch receipt for archived sources and artifacts')
    parser.add_argument('--check-only', action='store_true', help='validate receipts and destinations; write nothing')
    args = parser.parse_args(argv)
    result = register(args.project.resolve(), args.reaudit, args.fetch_receipt, check_only=args.check_only)
    print(json.dumps({'status': 'VERIFIED' if args.check_only else 'REGISTERED_EXPERIMENTAL_MODEL',
                      'models': NAMES, 'outputs': result, 'new_games': 0, 'new_optimizer_updates': 0}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
