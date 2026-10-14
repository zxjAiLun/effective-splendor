"""SSH/bootstrap entrypoint: verify the arena in its actual interpreter.

Control runs in the SDK interpreter; games run in the pinned arena interpreter.
Neither numerical dependencies nor pinned r8 sources are changed.
"""
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

REV=Path(__file__).resolve().parent
ROOT=REV.parent


def main():
    binding=json.loads((REV/(Path(__file__).stem+'-policy.json')).read_text())
    sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if sha(__file__)!=binding['source_sha256'] or sha(REV/'recovery.py')!=binding['recovery_sha256'] or sha(REV/'policy.json')!=binding['policy_sha256']:
        raise ValueError('endpoint source binding drift')
    sdk=REV/'sdk-control'
    manifest=REV/'sdk-manifest.json'
    if sha(manifest)!=binding['sdk_manifest_sha256']:
        raise ValueError('SDK manifest binding drift')
    for relative,expected in json.loads(manifest.read_text()).items():
        path=(sdk/relative).resolve()
        if not path.is_relative_to(sdk.resolve()) or sha(path)!=expected:
            raise ValueError('SDK source snapshot drift')
    sys.path.append(str(sdk))
    spec=importlib.util.spec_from_file_location('r8_recovery',REV/'recovery.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    native=module.load
    def load(name,path):
        controller=native(name,path)
        if name=='r6_preflight_r4':
            def verify_arena():
                execution=module.read(ROOT/'execution.json')
                py=controller.policy()['arena_python']
                result=subprocess.run([py,'-B',str(ROOT/'scripts/prism_m75_run.py'),'environment'],
                                      capture_output=True,text=True,check=True,timeout=30,
                                      env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
                actual=json.loads(result.stdout)
                expected=dict(execution['arena_environment'],affinity=list(range(8)))
                if actual!=expected:raise ValueError('DSW2 actual arena environment drift')
                controller.policy()
                return None,execution
            controller.verify_arena=verify_arena
        return controller
    module.load=load
    native_install=module.install_adapters
    def install(controller):
        native_install(controller)
        current_load=controller.load
        def restored_load(name,path):
            value=current_load(name,path)
            if name=='r4_handoff':
                factory=value.controller
                def factory_with_baseline():
                    dual,policy=factory()
                    original=native('r8_baseline_import',ROOT/'dual-node-r3/dual_node.py')
                    text=inspect.getsource(original.import_baseline)
                    old="or (ROOT/rel).exists()"
                    if text.count(old)!=1:raise ValueError('baseline import adapter target drift')
                    text=text.replace(old,"or ((ROOT/rel).exists() and digest(ROOT/rel)!=h)")
                    old='dest.write_bytes(z.read(rel))'
                    if text.count(old)!=1:raise ValueError('baseline write adapter target drift')
                    text=text.replace(old,'\n            if not dest.exists():dest.write_bytes(z.read(rel))')
                    namespace=dict(original.__dict__)
                    exec(compile(text,__file__+'::idempotent-baseline','exec'),namespace)
                    dual.import_baseline=namespace['import_baseline']
                    return dual,policy
                value.controller=factory_with_baseline
            return value
        controller.load=restored_load
    module.install_adapters=install
    return module.endpoint() if sys.argv[1]=='endpoint' else module.ensure()


if __name__=='__main__':
    try:print(json.dumps(main()))
    except Exception as error:
        print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__)))
        sys.exit(1)
