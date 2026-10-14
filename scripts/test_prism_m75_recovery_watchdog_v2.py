"""Zero-network tests for the stable broker's in-memory credential fallback."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('watch',Path(__file__).with_name('prism_m75_recovery_watchdog_v2.py'))
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

class WatchdogTests(unittest.TestCase):
    def test_cached_credential_survives_dsw_credential_loss_without_disk_secret(self):
        w.TOKEN='opaque-test-credential';requests=[];started=set()
        def rpc(node,request):
            if request['method']=='credential':raise RuntimeError('DSW replaced')
            if request['method']=='ensure':
                requests.append((node,request.copy()));started.add(node);return dict(state='STARTED')
            return dict(state='RUNNING' if node in started else 'NO_OWNER',node=node)
        with tempfile.TemporaryDirectory() as temporary,patch.object(w,'STATE',Path(temporary)),patch.object(w,'rpc',side_effect=rpc):
            result=w.cycle({})
            self.assertEqual({node for node,_ in requests},{'dsw','dsw2'})
            self.assertTrue(all(request['token']=='opaque-test-credential' for _,request in requests))
            self.assertEqual(result['credential_cache'],'AVAILABLE_MEMORY_ONLY')
            self.assertNotIn('opaque-test-credential',(Path(temporary)/'status.json').read_text())
            self.assertNotIn('opaque-test-credential',(Path(temporary)/'events.jsonl').read_text())

    def test_healthy_nodes_never_dispatch(self):
        calls=[];w.TOKEN=None
        def rpc(node,request):
            calls.append(request['method'])
            return dict(token='opaque') if request['method']=='credential' else dict(state='RUNNING',node=node)
        with tempfile.TemporaryDirectory() as temporary,patch.object(w,'STATE',Path(temporary)),patch.object(w,'rpc',side_effect=rpc):
            w.cycle({})
        self.assertNotIn('ensure',calls)

    def test_missing_credential_alerts_without_dsw2_start(self):
        w.TOKEN=None;calls=[]
        def rpc(node,request):
            if request['method']=='credential':raise RuntimeError('unavailable')
            calls.append((node,request['method']))
            return dict(state='NO_OWNER',node=node)
        with tempfile.TemporaryDirectory() as temporary,patch.object(w,'STATE',Path(temporary)),patch.object(w,'rpc',side_effect=rpc):
            result=w.cycle({})
        self.assertNotIn(('dsw2','ensure'),calls)
        self.assertEqual(result['nodes']['dsw2']['state'],'UNREACHABLE_OR_RECOVERY_BLOCKED')

if __name__=='__main__':unittest.main()
