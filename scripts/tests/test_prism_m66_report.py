"""Zero-game statistical and read-only reading adapter regression tests."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from scripts import prism_m66_report as report
from scripts import prism_greedy_reading as reader
from scripts import prism_round_report as common


class M66ReportTests(unittest.TestCase):
    def test_paired_orientation_and_incomplete_rejection(self):
        rows=[dict(candidate='c',opponent='o',seed=3,candidate_seat=s,candidate_score=v) for s,v in [(0,1),(1,0)]]
        seeds,values=report.block_values(rows,'c','o')
        self.assertEqual(seeds,[3]);self.assertEqual(values.tolist(),[.5])
        with self.assertRaisesRegex(ValueError,'duplicate'):report.block_values(rows+rows[:1],'c','o')
        with self.assertRaisesRegex(ValueError,'incomplete'):report.block_values(rows[:1],'c','o')

    def test_constant_bootstrap_and_equal_opponent_pairing(self):
        c=report.contract();e=c['evaluation'];reference=[];candidate=[];direct=[]
        for o in e['common_opponents']:
            for seed in range(e['common_seed_start'],e['common_seed_end']+1):
                for s in (0,1):
                    reference.append(dict(candidate='base',opponent=o,seed=seed,candidate_seat=s,candidate_score=.5))
                    candidate.append(dict(candidate='candidate',opponent=o,seed=seed,candidate_seat=s,candidate_score=.75))
        for seed in range(e['direct_seed_start'],e['direct_seed_end']+1):
            for s in (0,1):direct.append(dict(candidate='candidate',opponent='parent',seed=seed,candidate_seat=s,candidate_score=.5))
        measurements,gates,enhancements=report.competitive(c,reference,candidate,direct)
        self.assertEqual(measurements['candidate/strength_pool']['mean'],.25)
        self.assertEqual(measurements['candidate/strength_pool']['simultaneous_one_sided_lower'],.25)
        self.assertTrue(all(gates.values()));self.assertTrue(enhancements['candidate/strength_pool'])
        self.assertFalse(enhancements['candidate/direct_parent'])

    def test_bound_greedy_adapter_preserves_evidence_and_refuses_drift(self):
        root=common.ROOT
        source=root/'local-artifacts/prism/m65-release/harvest/release-evaluation/common'
        raw=json.loads((source/'result.json').read_text(encoding='utf-8'))
        config=json.loads((source/'config.json').read_text(encoding='utf-8'))
        weights={k:v['files'][0]['sha256'] for k,v in config['candidates'].items()}
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);result=temp/'result.json';specpath=temp/'spec.json';contract=temp/'contract.json'
            policy={'gates':{'strength':-.05}}
            contract.write_text(json.dumps({'evaluation':policy}),encoding='utf-8')
            r={'action_mode':'both-greedy','candidate_sha256':weights,'games':raw['games'],
               'source_result_sha256':[reader.sha(source/'result.json')],
               'gates':{'strength':True},'acceptance_policy':policy,
               'source_config_sha256':reader.sha(contract),
               'measurements':{'strength':{'simultaneous_one_sided_lower':0.}}}
            result.write_text(json.dumps(r),encoding='utf-8')
            ref={k:str(source/n) for k,n in [('result','result.json'),('plan','plan.json'),('config','config.json'),('completion','completion.json')]}
            ref.update(sha256=reader.sha(source/'result.json'),plan_sha256=reader.sha(source/'plan.json'),
                       config_sha256=reader.sha(source/'config.json'),completion_sha256=reader.sha(source/'completion.json'),stage='common',label='隔离保存数据测试')
            spec={'format':'prism-greedy-reading-spec-v1','result':str(result),'result_sha256':reader.sha(result),
                  'contract':str(contract),'contract_sha256':reader.sha(contract),
                  'markdown':str(source/'report.md'),'markdown_sha256':reader.sha(source/'report.md'),
                  'output':str(temp/'report.html'),'greedy_weight_sha256':weights,'greedy_results':[ref],
                  'focus':'beta','baseline':'base','names':{'beta':'未发布测试候选','base':'固定起点'},
                  'story':{'round':'TEST','title':'仅保存数据适配测试','headline':'不产生新竞技结论','identity':'保存结果只读测试',
                           'conclusions':[],'interpretation':'仅验证渲染','next':'不启动游戏'}}
            specpath.write_text(json.dumps(spec),encoding='utf-8');before=reader.sha(source/'report.md')
            receipt=common.build(specpath)
            self.assertEqual(receipt['games_dispatched'],0);self.assertEqual(receipt['sampling_history'],'NOT_RUN')
            self.assertEqual(reader.sha(source/'report.md'),before)
            document=(temp/'report.html').read_text(encoding='utf-8')
            payload=json.loads(re.search(r'<script[^>]*id="report-data"[^>]*>(.*?)</script>',document,re.S).group(1))
            self.assertIsNone(payload['links']['history'])
            self.assertEqual(payload['result']['common']['games'],raw['games'])
            self.assertNotIn(reader.sha(result),(temp/'report.reading.md').read_text(encoding='utf-8'))
            self.assertIn('模型物理座位',(temp/'report.reading.md').read_text(encoding='utf-8'))
            spec['greedy_results'][0]['completion_sha256']='0'*64;specpath.write_text(json.dumps(spec),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'completion drift'):common.build(specpath)


if __name__=='__main__':unittest.main()
