import unittest
from scripts import prism_m79_archive_r2 as adapter
from scripts.tests.test_prism_m79_archive import _verified_fixture

class MissingPairBoundary(unittest.TestCase):
    def test_undispatched_pair_is_preserved_without_profile_or_metrics(self):
        plan,result,v,policy=_verified_fixture();key=('a','anchor-complete')
        for row in result['pairs']:
            if (row['candidate'],row['opponent'])==key:row.update(candidate_metrics=None,opponent_metrics=None,completed_games=0,seats=[])
        removed={f"{r['model']}/{r['opponent']}/seed-{r['seed']}/seat-{r['seat']}" for r in v['attempts'] if (r['model'],r['opponent'])==key}
        attempts=[r for r in v['attempts'] if (r['model'],r['opponent'])!=key]
        profiles={k:p for k,p in v['profiles_by_game'].items() if k not in removed}
        receipt=dict(v['profile_receipt']);receipt['replays']=[r for r in receipt['replays'] if r['game_key'] not in removed];receipt['games_verified']=len(receipt['replays']);receipt['actor_profiles']=2*len(receipt['replays'])
        summary=adapter.aggregate(plan,result,attempts,profiles,receipt,v['identity_receipt']['model_sha256'],policy)
        row=next(r for r in summary['profile']['per_opponent'] if (r['model'],r['opponent'])==key)
        self.assertIsNone(row['profile']);self.assertIsNone(row['result']['candidate_metrics'])

    def test_completed_evidence_cannot_be_hidden_by_null_metrics(self):
        plan,result,v,policy=_verified_fixture()
        result['pairs'][0].update(candidate_metrics=None,opponent_metrics=None,completed_games=0,seats=[])
        with self.assertRaisesRegex(ValueError,'zero completed'):
            adapter.aggregate(plan,result,v['attempts'],v['profiles_by_game'],v['profile_receipt'],v['identity_receipt']['model_sha256'],policy)

if __name__=='__main__':unittest.main()
