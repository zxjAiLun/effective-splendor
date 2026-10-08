"""Bounded generic arena contract, quota and recovery checks (no model training)."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from scripts import prism_notebook_arena as a
from scripts import prism_notebook_bundle as b
from scripts import prism_notebook_report as r


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.engine=self.root/'engine';self.engine.write_bytes(b'native')
        self.metrics=self.root/'metrics';self.metrics.write_bytes(b'metrics')
        self.weights=self.root/'weights.json';a.write(self.weights,dict(format='prism-weights-v1',catalog_fingerprint='catalog'))
        self.profile=dict(effective_whole_cores=8,recommended_workers=6,effective_memory_bytes=28*1024**3,
                          host_available_memory_bytes=26*1024**3,limit_scope='test')
        self.profile_patch=patch.object(a,'resource_profile',return_value=self.profile);self.profile_patch.start();self.addCleanup(self.profile_patch.stop)
        self.work=self.root/'run'

    def prepare(self,**kwargs):
        with patch.object(a.subprocess,'run',return_value=SimpleNamespace(stdout='test')):
            return a.prepare(self.work,self.engine,self.metrics,{'base':a.model(self.weights,'Prism Balance v0.1.0',self.engine)},
                             {'heuristic':a.heuristic(self.engine)},[1,2,3],shard_seed_blocks=1,**kwargs)

    def test_prepare_zero_games_unique_paired_grid(self):
        p=self.prepare();self.assertEqual(p['total_games'],6);self.assertEqual(len(p['shards']),3)
        self.assertEqual(a.status(self.work)['state'],'PREPARED_ZERO_GAMES');self.assertFalse((self.work/'shards').exists())
        self.assertEqual(p['limits']['workers'],6)

    def test_greedy_config_and_effective_command_agree_without_mutation(self):
        with patch.object(a.subprocess,'run',return_value=SimpleNamespace(stdout='test')):
            a.prepare(self.work,self.engine,self.metrics,
                {'candidate':a.model(self.weights,'Prism candidate（未发布）',self.engine,mode='greedy')},
                {'heuristic':a.heuristic(self.engine)},[1,2])
        saved=a.read(self.work/'config.json');before=copy.deepcopy(saved)
        v=a.validate_arena_config(saved,self.work/'config.json')
        self.assertEqual(saved,before)
        self.assertEqual(v['config']['candidates']['candidate']['args'][0],'agent-prism')
        self.assertEqual(v['candidates']['candidate']['args_resolved'][0],'agent-prism')
        with self.assertRaisesRegex(ValueError,'agent-prism-sample'):
            a.fixed.validate_config(saved,self.work/'config.json')
        a.verify(self.work)

    def test_greedy_still_rejects_wrong_seed_and_unpinned_weight(self):
        self.prepare();c=a.read(self.work/'config.json');c['candidates']['base']['args'][0]='agent-prism'
        c['candidates']['base']['args'][4]='123'
        with self.assertRaisesRegex(ValueError,'action_seed'):a.validate_arena_config(c,self.work/'config.json')
        c['candidates']['base']['args'][4]=str(c['action_seed']);c['candidates']['base']['files']=[]
        with self.assertRaisesRegex(ValueError,'pinned SHA'):a.validate_arena_config(c,self.work/'config.json')

    def test_refuse_overwrite(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'new run directory'):self.prepare()

    def test_worker_cpu_quota_bound(self):
        with self.assertRaisesRegex(ValueError,'CPU'):self.prepare(workers=9)

    def test_explicit_four_core_calibration_oversubscription(self):
        self.profile['effective_whole_cores']=4
        with self.assertRaisesRegex(ValueError,'CPU'):self.prepare(workers=6)
        p=self.prepare(workers=6,performance_calibration=True,wall_hours=.1,memory_gib=8)
        self.assertEqual(p['verdict'],'PERFORMANCE_DIAGNOSTIC_NOT_STRENGTH')
        a.verify(self.work)
        with self.assertRaisesRegex(ValueError,'four-core'):
            a.worker_limit({'effective_whole_cores':2},True)
        with self.assertRaisesRegex(ValueError,'boolean'):
            a.worker_limit(self.profile,1)

    def test_calibration_cannot_expand_ordinary_game_or_wall_budget(self):
        self.profile['effective_whole_cores']=4
        with self.assertRaisesRegex(ValueError,'CPU'):self.prepare(workers=7,performance_calibration=True)
        with self.assertRaisesRegex(ValueError,'calibration is limited'):
            self.prepare(workers=6,performance_calibration=True,wall_hours=2)

    def test_memory_bound(self):
        with self.assertRaisesRegex(ValueError,'memory budget'):self.prepare(memory_gib=24)

    def test_asset_drift(self):
        self.prepare();self.weights.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):a.verify(self.work)

    def test_source_drift(self):
        self.prepare()
        with patch.object(a,'sha',side_effect=lambda p:'0'*64 if str(p).endswith('prism_dsw_arena.py') else b.sha(p)):
            with self.assertRaisesRegex(ValueError,'source changed'):a.verify(self.work)

    def test_dependency_drift(self):
        self.prepare()
        with patch.object(a.importlib.metadata,'version',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'dependency'):a.verify(self.work)

    def test_shard_overlap_even_after_rehash(self):
        p=self.prepare();s=p['shards'][1];v=a.read(s['config']);v['seeds']=[1];a.write(s['config'],v)
        s['sha256']=a.sha(s['config']);a.write(self.work/'plan.json',p)
        with self.assertRaisesRegex(ValueError,'duplicate'):a.verify(self.work)

    def test_plan_drift_refuses_launch(self):
        p=self.prepare();p['limits']['workers']=1;a.write(self.work/'plan.json',p)
        with self.assertRaisesRegex(ValueError,'plan changed'):a.start(self.work)

    def test_partial_shard_refuses_launch(self):
        self.prepare();s=a.read(self.work/'status.json');s.update(state='STOPPED_SAFE',shards={'shard-00000':{'state':'DISPATCHED'}})
        a.write(self.work/'status.json',s)
        with self.assertRaisesRegex(ValueError,'partial'):a.start(self.work)

    def test_under_lock_live_owner_recheck(self):
        self.prepare()
        # First pre-lock check sees no owner, but the prior caller writes one
        # immediately before this caller acquires the lock.
        original=a.os.open
        def race(path,*args):
            fd=original(path,*args);a.write(self.work/'owner.json',{'pid':123});return fd
        with patch.object(a.os,'open',side_effect=race),patch.object(a,'alive',return_value=True):
            with self.assertRaisesRegex(ValueError,'live runner'):a.start(self.work)
        self.assertFalse((self.work/'launch.lock').exists())

    def dead_owner(self,state='RUNNING',shards=None):
        self.prepare();s=a.read(self.work/'status.json');s.update(state=state,shards=shards or {})
        a.write(self.work/'status.json',s);a.write(self.work/'owner.json',dict(pid=-1,token='previous',instance_key='old'))
        (self.work/'attempts'/'previous').mkdir(parents=True)

    def test_dead_instance_is_interrupted(self):
        self.dead_owner();self.assertEqual(a.status(self.work)['state'],'INTERRUPTED_NO_AUTO_RETRY')

    def test_recover_no_dispatched_work(self):
        self.dead_owner();self.assertEqual(a.recover(self.work)['state'],'STOPPED_SAFE')

    def test_recover_partial_never_respawns(self):
        self.dead_owner(shards={'shard-00000':dict(state='DISPATCHED',games=2)})
        s=a.recover(self.work);self.assertEqual(s['state'],'FAILED_PARTIAL_NO_RETRY')
        with self.assertRaisesRegex(ValueError,'only new'):a.start(self.work)

    def test_recover_complete_uncommitted_receipt(self):
        self.dead_owner(shards={'shard-00000':dict(state='DISPATCHED',games=2)})
        p=a.read(self.work/'plan.json');out=Path(p['shards'][0]['output']);out.mkdir(parents=True);a.write(out/'completion.json',{'test':True})
        with patch.object(a,'completed_shard') as check:
            s=a.recover(self.work);self.assertEqual(s['state'],'STOPPED_SAFE');self.assertEqual(s['completed_games'],2)
            check.assert_called_once()

    def test_recover_live_runner_refused(self):
        self.dead_owner()
        with patch.object(a,'alive',return_value=True):
            with self.assertRaisesRegex(ValueError,'live'):a.recover(self.work)

    def test_wrong_instance_never_owns_reused_pid(self):
        with patch.object(a,'instance_key',return_value='new'),patch.object(a.psutil,'Process') as process:
            self.assertFalse(a.alive({'instance_key':'old','pid':1}));process.assert_not_called()

    def test_worker_refuses_existing_output(self):
        self.work.mkdir()
        with self.assertRaisesRegex(ValueError,'never respawns'):a.worker(self.root/'none.json',self.work)

    def test_archive_outside_run_only(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'outside'):a.export_zip(self.work,self.work/'x.zip')

    def test_completed_clock_provenance_drift_rejected(self):
        p=self.prepare();shard=p['shards'][0];out=Path(shard['output']);out.mkdir(parents=True)
        config=a.read(shard['config']);config['candidates']['base']['args'][0]='agent-prism';a.write(shard['config'],config)
        progress=dict(config_sha256=a.fixed.canonical_hash(a.read(shard['config'])),games={})
        for seat in (0,1):
            row=dict(candidate='base',opponent='heuristic',seed=1,candidate_seat=seat)
            game=out/'games/base/heuristic'/f'seed-1-seat-{seat}';game.mkdir(parents=True)
            for name in ('report.json','replay.json','process-result.json','match-config.json'):a.write(game/name,{'test':True})
            a.write(game/'game.json',dict(row=row,status='completed'))
            progress['games'][a.fixed._game_key('base','heuristic',1,seat)]=dict(status='completed',row=row,
                report_sha256=a.sha(game/'report.json'),replay_sha256=a.sha(game/'replay.json'),
                artifact_hashes={n:a.sha(game/n) for n in ('game.json','process-result.json','match-config.json')})
        a.write(out/'progress.json',progress)
        a.write(out/'completion.json',dict(config_sha256=progress['config_sha256'],games=2,progress_sha256=a.sha(out/'progress.json')))
        receipt=dict(completion_sha256=a.sha(out/'completion.json'))
        self.assertEqual(len(a.completed_shard(shard,receipt)),2)
        a.write(game/'process-result.json',{'test':'changed'})
        with self.assertRaisesRegex(ValueError,'provenance changed'):a.completed_shard(shard,receipt)

    def test_instance_deadline_renews_for_current_pid1(self):
        plan=dict(limits=dict(instance_hours=8,expiry_margin_minutes=45))
        with patch.object(a.sys,'platform','linux'),patch.object(a.psutil,'Process') as process:
            process.return_value.create_time.return_value=1000
            self.assertEqual(a.instance_deadline(plan),1000+8*3600-45*60)
            process.return_value.create_time.return_value=2000
            self.assertEqual(a.instance_deadline(plan),2000+8*3600-45*60)


class QuotaTests(unittest.TestCase):
    def test_arm_elf_rejected_on_x86_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'binary';header=bytearray(64);header[:4]=b'\x7fELF';header[5]=1;header[18:20]=(183).to_bytes(2,'little');p.write_bytes(header)
            with patch.object(a.sys,'platform','linux'),patch.object(a.platform,'machine',return_value='x86_64'):
                with self.assertRaisesRegex(ValueError,'architecture mismatch'):a.check_native_architecture(p)

    def profile(self,root,lines):
        with patch.object(a.sys,'platform','linux'),patch.object(a.os,'cpu_count',return_value=64),\
             patch.object(a.os,'sched_getaffinity',return_value=set(range(64)),create=True),\
             patch.object(a.psutil,'virtual_memory',return_value=SimpleNamespace(total=128*1024**3,available=100*1024**3)):
            return a.resource_profile(root,lines)

    def test_v1_parent_quota_and_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for c in ('cpu','memory'):(root/c/'pod').mkdir(parents=True)
            (root/'cpu'/'cpu.cfs_quota_us').write_text('800000');(root/'cpu'/'cpu.cfs_period_us').write_text('100000')
            (root/'cpu'/'pod'/'cpu.cfs_quota_us').write_text('1200000');(root/'cpu'/'pod'/'cpu.cfs_period_us').write_text('100000')
            (root/'memory'/'memory.limit_in_bytes').write_text(str(28*1024**3))
            p=self.profile(root,['2:cpu,cpuacct:/pod','3:memory:/pod'])
            self.assertEqual(p['effective_cpu_capacity'],8);self.assertEqual(p['recommended_workers'],6)
            self.assertEqual(p['effective_memory_bytes'],28*1024**3)

    def test_v2_nested_parent_quota(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pod').mkdir();(root/'cpu.max').write_text('400000 100000')
            (root/'pod'/'cpu.max').write_text('max 100000');(root/'memory.max').write_text(str(16*1024**3))
            self.assertEqual(self.profile(root,['0::/pod'])['recommended_workers'],3)


class ReportAndBundleTests(unittest.TestCase):
    def test_paired_pure_win_and_half_draw_differ(self):
        rows=[dict(seed=1,candidate_seat=0,record='win',candidate_score=1),dict(seed=1,candidate_seat=1,record='draw',candidate_score=.5)]
        self.assertEqual(r.interval(rows)['estimate'],.75);self.assertEqual(r.interval(rows,True)['estimate'],.5)

    def test_duplicate_seat_refused(self):
        row=dict(seed=1,candidate_seat=0,record='win',candidate_score=1)
        with self.assertRaisesRegex(ValueError,'duplicate'):r.interval([row,row])

    def test_incomplete_pair_refused(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):r.interval([dict(seed=1,candidate_seat=0,record='win',candidate_score=1)])

    def archive(self,temp,name,raw=b'payload',digest=None):
        p=Path(temp)/'bundle.zip'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr(name,raw);z.writestr('manifest.json',json.dumps(dict(format='prism-notebook-model-bundle-v1',
                 files={name:digest or hashlib.sha256(raw).hexdigest()})))
        return p

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.archive(temp,'models/../../escape')
            with self.assertRaisesRegex(ValueError,'unsafe'):b.unpack(p,Path(temp)/'dest',b.sha(p))

    def test_member_sha_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.archive(temp,'models/base.json',digest='0'*64);dest=Path(temp)/'dest'
            with self.assertRaisesRegex(ValueError,'member SHA'):b.unpack(p,dest,b.sha(p))
            self.assertFalse(dest.exists())

    def test_model_conflicting_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.archive(temp,'models/base.json');dest=Path(temp)/'dest';(dest/'models').mkdir(parents=True)
            (dest/'models'/'base.json').write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError,'conflicting'):b.unpack(p,dest,b.sha(p))


if __name__=='__main__':unittest.main()
