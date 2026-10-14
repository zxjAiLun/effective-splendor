import importlib.util,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'scripts/prism_m75_wait_resume.py'
if not p.exists():p=Path(__file__).resolve().parent/'resume.py'
s=importlib.util.spec_from_file_location('wait_resume',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class WaitResume(unittest.TestCase):
    def fixture(self):
        return {'state':'PASS','resources':{'returncode':0,'stop_reason':None,'cpu_seconds':385.75}}, {'completed_games':768,'truncated_games':0,'shards':[{'label':str(i),'planned_games':64} for i in range(12)]}
    def test_original_cpu_is_not_reset(self):self.assertEqual(m.validate_completed(*self.fixture()),385.75)
    def test_incomplete_cannot_skip(self):
        stage,done=self.fixture();done['completed_games']=767
        with self.assertRaises(ValueError):m.validate_completed(stage,done)
    def test_duplicate_shards_rejected(self):
        stage,done=self.fixture();done['shards'][-1]['label']='0'
        with self.assertRaises(ValueError):m.validate_completed(stage,done)
    def test_failure_cannot_skip(self):
        stage,done=self.fixture();stage['resources']['stop_reason']='wall_deadline'
        with self.assertRaises(ValueError):m.validate_completed(stage,done)
if __name__=='__main__':unittest.main()
