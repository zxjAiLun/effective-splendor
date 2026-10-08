import copy
import tempfile
import unittest
from pathlib import Path
from scripts.prism_generation_release import derived_manifest, preflight, publish, write
from scripts.prism_model_release import sha


class GenerationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        parent=self.root/'parent.json';write(parent,{'parent':'unchanged'});self.models=[]
        for i in range(3):
            base=self.root/f'input/{i}';weight=base/'weights.json'
            write(weight,{'format':'prism-weights-v1','catalog_fingerprint':'catalog','state_dict':{f't{k}':{'shape':[1],'data':[k+i/10]} for k in range(32)}})
            cp={'status':'PASS','cycle':4,'commit':'original','run_identity':str(i),'initialization':{'parent_sha256':sha(parent)},'exact_export_tensors':32}
            audit={'status':'PASS_TRAINING_ARTIFACT_AUDIT','weights_sha256':sha(weight),'checkpoint':cp};write(base/'audit.json',audit)
            write(base/'manifest.json',derived_manifest(weight,audit))
            config={'base_model':{'sha256':sha(parent)},'training':{'arms':{'a':{'cycles':4}}}};write(base/'config.json',config)
            result={'source_config_sha256':sha(base/'config.json'),'action_mode':'both-greedy','candidate_sha256':{'base':sha(parent),'candidate':sha(weight)},'training_audit_sha256':sha(base/'audit.json'),'verdicts':{'overall_enhancement':False,'published':False}};write(base/'result.json',result)
            rel=lambda p:p.relative_to(self.root).as_posix()
            m={'model_id':f'prism-balance-v0.2.{i}','display_name':f'Prism Balance v0.2.{i}','origin':{'milestone':'M70','cycle':4,'arm':'a'},'source_weights':rel(weight),'source_companion':rel(base/'manifest.json'),'weights_sha256':sha(weight),'original_config':rel(base/'config.json'),'original_result':rel(base/'result.json'),'artifact_audit':rel(base/'audit.json'),'result_key':'candidate','parent':{'sha256':sha(parent),'source_weights':rel(parent)},'greedy_evidence':[],'weights_path':f'local-artifacts/prism/balance-v0.2.{i}/weights.json','record_path':f'benchmarks/v{i}.model.json','source_hashes':{rel(p):sha(p) for p in base.iterdir()}}
            self.models.append(m)
        self.spec={'authorization':{'source':'human_owner'},'models':self.models,'receipt_path':'receipt.json'}

    def test_three_publish_preserves_original_negative_verdict_and_exact_bytes(self):
        spec=self.root/'spec.json';write(spec,self.spec);r=publish(spec,self.root)
        self.assertEqual(len(r['models']),3)
        for m in self.models:
            self.assertEqual(sha(self.root/m['weights_path']),m['weights_sha256'])
        from scripts.prism_model_release import read
        record=read(self.root/self.models[0]['record_path'])
        self.assertFalse(record['original_research_verdict']['overall_enhancement']);self.assertFalse(record['default_replaced'])

    def test_late_source_drift_rejects_before_any_output(self):
        (self.root/self.models[2]['artifact_audit']).write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source drift'):preflight(self.spec,self.root)
        self.assertFalse((self.root/'local-artifacts').exists())

    def test_late_version_collision_rejects_before_any_output(self):
        write(self.root/self.models[2]['record_path'],{'existing':'version'})
        with self.assertRaisesRegex(ValueError,'already registered'):preflight(self.spec,self.root)
        self.assertFalse((self.root/'local-artifacts').exists())

    def test_parent_identity_drift_rejected(self):
        self.models[1]['parent']['sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'parent drift'):preflight(self.spec,self.root)

    def test_wrong_final_cycle_rejected(self):
        self.models[0]['origin']['cycle']=3
        with self.assertRaisesRegex(ValueError,'cycle drift'):preflight(self.spec,self.root)

    def test_duplicate_destination_rejected(self):
        self.models[2]['weights_path']=self.models[0]['weights_path']
        with self.assertRaisesRegex(ValueError,'duplicate output'):preflight(self.spec,self.root)

    def test_missing_human_authorization_rejected(self):
        self.spec['authorization']['source']='agent'
        with self.assertRaisesRegex(ValueError,'authorization'):preflight(self.spec,self.root)

    def test_path_escape_rejected(self):
        self.models[0]['record_path']='../external.model.json'
        with self.assertRaisesRegex(ValueError,'outside project'):preflight(self.spec,self.root)


if __name__=='__main__':unittest.main()
