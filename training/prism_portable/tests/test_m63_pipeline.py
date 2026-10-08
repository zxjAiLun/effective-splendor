"""Pipeline completion is an artifact contract, independent of scientific PASS."""
import copy
import unittest
from scripts import prism_m63_pipeline_driver as driver


class PipelineTests(unittest.TestCase):
    def fixtures(self):
        completion={'status':'COMPLETED_FIXED_BUILDING_EVALUATION','physical_games':10304,
                    'retry':0,'formal_gates_analyzed_once':True}
        result={'format':'m63-building-evaluation-result-v1','status':completion['status'],
                'physical_games':10304,'retries':0,'development':{'games':576},
                'acceptance':{'games':9728},'verdicts':{'beta':'NOT_ACCEPTED_BUILDING_CANDIDATE'}}
        return completion,result

    def test_completed_negative_scientific_result_is_valid(self):
        c,r=self.fixtures()
        self.assertEqual(driver.completed_evaluation(c,r),r['verdicts'])

    def test_incomplete_or_wrong_schema_does_not_finish_pipeline(self):
        c,r=self.fixtures()
        for field,value in [('status','COMPLETED_FIXED_AB_EVALUATION'),('physical_games',9280),
                            ('retry',1),('formal_gates_analyzed_once',False)]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                driver.completed_evaluation(dict(c,**{field:value}),r)
        for field,value in [('format','m62-building-evaluation-result-v1'),('verdicts',None),
                            ('physical_games',10303),('retries',1),('development',{'games':575}),
                            ('acceptance',{'games':9727})]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                driver.completed_evaluation(c,dict(r,**{field:value}))

    def test_audit_inherits_real_eight_gibibyte_ceiling(self):
        contract={'memory_bytes':8*1024**3,'cpu_quota_percent':200,'wall_seconds':97200,
                  'automatic_retries':0,'audit_scope':'children inherit pipeline cgroup'}
        props={'MainPID':'5432','MemoryMax':str(8*1024**3),'CPUQuotaPerSecUSec':'2s','RuntimeMaxUSec':'1d 3h'}
        for duration in ('1d 3h','27h','97200000000'):
            driver.validate_resources(dict(props,RuntimeMaxUSec=duration),5432,contract)
        for field,value in [('MainPID','0'),('MemoryMax',str(1024**3)),('CPUQuotaPerSecUSec','200ms'),
                            ('RuntimeMaxUSec','infinity')]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                driver.validate_resources(dict(props,**{field:value}),5432,contract)
        with self.assertRaises(ValueError):
            driver.validate_resources(props,5432,dict(contract,automatic_retries=1))


if __name__=='__main__': unittest.main()
