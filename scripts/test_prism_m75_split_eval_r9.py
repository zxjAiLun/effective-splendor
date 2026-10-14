import ast,pathlib,unittest,threading,tempfile,json
from types import SimpleNamespace
source=pathlib.Path('scripts/prism_m75_split_eval_r9.py').read_text();tree=ast.parse(source);func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='partition');ns={};exec(compile(ast.Module(body=[func],type_ignores=[]),'partition','exec'),ns);partition=ns['partition']
class SplitTests(unittest.TestCase):
 def test_disjoint_complete_cover(self):
  shards=[dict(label=str(i)) for i in range(80)];completed={str(i) for i in range(64)};dsw={s['label'] for s in partition(shards,completed)};dsw2={s['label'] for s in shards}-completed-dsw
  self.assertEqual(len(dsw),5);self.assertEqual(len(dsw2),11);self.assertFalse(dsw&completed);self.assertFalse(dsw&dsw2);self.assertEqual(completed|dsw|dsw2,{s['label'] for s in shards})
 def test_finished_not_dispatched(self):self.assertEqual(partition([dict(label='x')],{'x'}),[])
 def test_duplicates_refused(self):
  with self.assertRaises(ValueError):partition([dict(label='x'),dict(label='x')],set())
 def test_pending_starts_before_finished_validation(self):
  ordering=ast.parse(pathlib.Path('scripts/prism_m75_split_eval_ordering_v2.py').read_text())
  overlap=next(n for n in ast.walk(ordering) if isinstance(n,ast.FunctionDef) and n.name=='overlap')
  started=threading.Event()
  def original(pending,**kw):
   self.assertEqual([s['label'] for s in pending],['new']);started.set();return [dict(pending[0],grid={'truncated_games':0})]
  def audit(path):
   self.assertTrue(started.wait(1));return {'truncated_games':0}
  scope=dict(Path=pathlib.Path,threading=threading,q=SimpleNamespace(read=lambda p:json.loads(p.read_text())),b=SimpleNamespace(inspect=audit),original=original)
  exec(compile(ast.Module(body=[overlap],type_ignores=[]),'overlap','exec'),scope)
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);old=root/'old';old.mkdir();(old/'ledger.json').write_text('{"execution_state":"FINISHED"}')
   result=scope['overlap']([dict(label='old',output=str(old)),dict(label='new',output=str(root/'new'))])
   self.assertEqual({s['label'] for s in result},{'old','new'})
 def test_successful_combined_stage_charged_once(self):
  tree=ast.parse(pathlib.Path('scripts/prism_m75_split_eval_ordering_v3.py').read_text())
  stage=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='stage')
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);(root/'final-evaluation').mkdir();(root/'final-evaluation/completion.json').write_text(json.dumps(dict(state='PASS',split_policy_sha256='bound',resources={'cpu_seconds':321})))
   def refuse(*args):self.fail('must not add DSW cost again')
   scope=dict(m=SimpleNamespace(REV=root),q=SimpleNamespace(REV=root,read=lambda p:json.loads(p.read_text()),digest=lambda p:'bound'),original_stage=refuse)
   exec(compile(ast.Module(body=[stage],type_ignores=[]),'stage','exec'),scope)
   self.assertEqual(scope['stage']('final-evaluation',1000,'dsw2'),321)
unittest.main()
