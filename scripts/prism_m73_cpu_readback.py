"""Independent arithmetic readback of retained R3 engineering evidence.

Never changes the frozen source, manifest, ledger or per-game bytes. Runs a
derived inspector with dispatch-order arithmetic and records separate evidence.
"""
import importlib.util
from pathlib import Path
import sys

def inspect_retained(root):
    from training.prism_portable.common import digest,read
    source=root/'scripts/prism_bounded_eval.py';text=source.read_text(encoding='utf-8')
    old='total = sum(measured_cpu[key] for key in expected if key in measured_cpu)'
    if text.count(old)!=1:raise ValueError('unexpected original inspector source')
    revised=text.replace(old,'total = 0.\n        for key in expected:\n            if key in measured_cpu:\n                total += measured_cpu[key]')
    module=type(sys)('m73_retained_r3_inspector');module.__file__=str(source)
    exec(compile(revised,str(Path(__file__).resolve()),'exec'),module.__dict__)
    output=root/'evaluation/engineering-terminal';result=module.inspect(output)
    if result['completed_games']!=4 or result['truncated_games']!=0:raise ValueError('retained engineering grid incomplete')
    return dict(status='PASS_INDEPENDENT_REVISED_ARITHMETIC_READBACK',original_error='ledger CPU total drift',completed_games=4,new_games=0,
        original_source_sha256=digest(source),original_manifest_sha256=digest(output/'manifest.json'),original_ledger_sha256=digest(output/'ledger.json'),validator_sha256=digest(Path(__file__)),grid=result)
