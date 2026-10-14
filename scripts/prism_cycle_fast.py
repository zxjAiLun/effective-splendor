"""Execution-only caches for the synchronous, source-pinned PPO campaign.

No cache is persisted. Content-addressed game bytes are still verified when a
compact summary is reused. Failed seals and restart/reload take the strict path.
The launch index observes successful records only; a changed ledger head rebuilds
it. Neither checkpoint format nor commit frequency is changed.
"""
from collections import Counter
from contextlib import contextmanager
import copy
import inspect


class AttemptIndex:
    def __init__(self, campaign):
        self.campaign = campaign
        self.head = None
        self.rows = {}
        self.by_job = {}
        self.counts = Counter()
        self.rebuilds = 0

    def invalidate(self):
        self.head = None

    def _replace(self, number, row):
        number = str(number)
        if number in self.rows:
            job, status = self.rows[number]
            self.counts[status] -= 1
            del self.by_job[job][number]
            if not self.by_job[job]:
                del self.by_job[job]
        job, status = row.get('job', {}).get('job_id'), row['status']
        self.rows[number] = (job, status)
        self.by_job.setdefault(job, {})[number] = status
        self.counts[status] += 1

    def ensure(self):
        head, ledger = self.campaign._load()
        if self.head != head:
            self.rows.clear(); self.by_job.clear(); self.counts.clear()
            for number, row in ledger['attempts'].items():
                self._replace(number, row)
            self.head = head
            self.rebuilds += 1
        return self

    def previous(self, job_id):
        self.ensure()
        # The frozen launch wrapper reads only status from this view.
        return [{'status': status} for status in self.by_job.get(job_id, {}).values()]

    def count(self, status):
        return self.ensure().counts[status]

    def recorded(self, number):
        head, ledger = self.campaign._load()
        expected = len(self.rows) + int(str(number) not in self.rows)
        if len(ledger['attempts']) != expected:
            self.invalidate(); self.ensure()
            return
        self._replace(number, ledger['attempts'][str(number)])
        self.head = head

    def reconcile(self):
        self.ensure()
        _, ledger = self.campaign._load()
        actual = {str(n): (r.get('job', {}).get('job_id'), r['status'])
                  for n, r in ledger['attempts'].items()}
        if actual != self.rows:
            self.invalidate()
            raise ValueError('attempt index drift')


def summary_key(run):
    s = run.state
    return (s['cycle'], s['snapshot'], tuple(
        (j['job_id'], j['actor'], j['opponent_id'], j['environment_seed'],
         s['jobs'].get(j['job_id'], {}).get('status'),
         s['jobs'].get(j['job_id'], {}).get('artifact')) for j in s['schedule']))


class CycleCache:
    """Only ranks/counts are retained, never the game's feature arrays."""
    def __init__(self, run):
        self.run = run
        self.compact = {}
        self.key = None
        self.sealing = self.summarizing = False
        self.published_batch = None
        self.metrics = Counter()
        self.get_json = run.store.get_json
        self.put_json = run.store.put_json

    def read(self, digest):
        if self.summarizing and digest in self.compact:
            # Keep the old corruption/missing-object rejection, without parsing
            # the large verified JSON again just to count decisions.
            self.run.store._get('objects', digest, '.json')
            self.metrics['summary_reuses'] += 1
            row = self.compact[digest]
            return {'result': {'ranks': list(row[0])}, 'decisions': range(row[1])}
        value = self.get_json(digest)
        if self.sealing and isinstance(value, dict) and value.get('format') == 'prism-ppo-game-v1':
            self.compact[digest] = (tuple(value['result']['ranks']), len(value['decisions']))
            self.metrics['summaries_captured'] += 1
        return value

    def put(self, value):
        digest = self.put_json(value)
        if self.sealing and isinstance(value, dict) and value.get('format') == 'prism-ppo-batch-v1':
            # In the pinned seal, validate_batch precedes put_json, which must
            # succeed before this receipt exists. It is cleared at scope exit.
            self.published_batch = (digest, value, value['batch_id'])
        return digest

    def validate_binding(self, run, batch, strict):
        receipt = self.published_batch
        if (self.sealing and run is self.run and receipt is not None
                and run.state['batch'] == receipt[0] and batch is receipt[1]
                and batch.get('batch_id') == receipt[2]
                and run._batch_cache is not None
                and run._batch_cache[0] == receipt[0] and run._batch_cache[1] is batch):
            self.metrics['binding_reuses'] += 1
            return None
        self.metrics['binding_strict'] += 1
        return strict(batch, run.ppo)

    @contextmanager
    def seal_scope(self):
        if self.sealing or self.summarizing:
            raise RuntimeError('nested cycle cache scope')
        self.compact.clear(); self.key = None
        self.published_batch = None
        self.sealing = True
        try:
            yield
            self.key = summary_key(self.run)
        except BaseException:
            self.compact.clear()
            raise
        finally:
            self.sealing = False
            self.published_batch = None

    @contextmanager
    def summary_scope(self):
        if self.sealing or self.summarizing:
            raise RuntimeError('nested cycle cache scope')
        if self.key != summary_key(self.run):
            self.compact.clear(); self.key = None
        self.summarizing = True
        try:
            yield
        finally:
            self.summarizing = False


def install_cycle_cache(campaign, legacy):
    if hasattr(campaign, '_cycle_cache'):
        raise ValueError('cycle cache already installed')
    run = campaign.run
    cache = CycleCache(run)
    campaign._cycle_cache = cache
    run.store.get_json, run.store.put_json = cache.read, cache.put
    seal, summary = run.seal, campaign.cycle_summary

    def cached_seal():
        with cache.seal_scope():
            return seal()

    def cached_summary():
        with cache.summary_scope():
            return summary()

    def validate_binding(target, batch, strict):
        return cache.validate_binding(target, batch, strict)

    run.seal = cached_seal
    campaign.cycle_summary = cached_summary
    legacy.record_batch = legacy.adapted(legacy.record_batch, [
        ('validate_batch(batch,run.ppo)', '_validate_binding(run,batch,validate_batch)')],
        {'_validate_binding': validate_binding})
    return cache


def install_attempt_index(campaign, legacy, arena):
    index = AttemptIndex(campaign)
    index.ensure()
    campaign._attempt_index = index
    original_record = campaign.record

    def record(number, data, **kwargs):
        index.ensure()
        try:
            result = original_record(number, data, **kwargs)
            index.recorded(number)
            return result
        except BaseException:
            index.invalidate()
            raise

    campaign.record = record
    counts = lambda c, status: c._attempt_index.count(status)
    progress = legacy.adapted(legacy.publish_progress, [
        ("sum(x['status']=='COMPLETE' for x in ledger['attempts'].values())", "_counts(campaign,'COMPLETE')"),
        ("sum(x['status']=='TRUNCATED' for x in ledger['attempts'].values())", "_counts(campaign,'TRUNCATED')"),
        ("sum(x['status']=='INFRA_ABORT' for x in ledger['attempts'].values())", "_counts(campaign,'INFRA_ABORT')")],
        {'_counts': counts})
    legacy.publish_progress = progress
    outer = arena.Campaign.launch
    outer_bindings = inspect.getclosurevars(outer).nonlocals
    wrapped = outer_bindings['original_launch']
    bindings = inspect.getclosurevars(wrapped).nonlocals
    fast = legacy.adapted(wrapped, [
        ("[r for r in ledger['attempts'].values() if r.get('job',{}).get('job_id')==job['job_id']]",
         "self._attempt_index.previous(job['job_id'])"),
        ("sum(r['status']=='INFRA_ABORT' for r in ledger['attempts'].values())",
         "self._attempt_index.count('INFRA_ABORT')"),
        ("sum(r['status']=='INFRA_ABORT' and r.get('job',{}).get('job_id')==job['job_id'] for r in ledger['attempts'].values())",
         "sum(r['status']=='INFRA_ABORT' for r in self._attempt_index.previous(job['job_id']))")],
        dict(bindings, publish_progress=progress))
    # r3 wrapped this closure after legacy.install. Do not bypass its timing,
    # storage watch, DSW launcher or the native retry/commit implementation.
    arena.Campaign.launch = legacy.adapted(outer, [], dict(outer_bindings, original_launch=fast))
    return index
