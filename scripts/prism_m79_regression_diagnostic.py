"""Read-only replay diagnostics for the two M79 regression opponents.

Runs against the frozen M79 tree and its verified Rust projector. No inference,
new games, counterfactual rollout, or changes to training/evaluation artifacts.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

COLORS = ['white', 'blue', 'green', 'red', 'black']
TIERS = ['One', 'Two', 'Three']
CACHE_SHA = '4d221d3e00d802f695859885e96422cf4ff842b2c3cf77cdb8885d30acd1a129'
PROJECTOR_SHA = '1c605d536a4e2d05be23142ba4115c60c7445ea9400a524ec474cec50995b58f'
RESULT_SHA = '50a76a85fbfef46e41d296efa23915b4f76c4fae0672151e9e6ecd960735f85a'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def affordable(card, player, catalog):
    costs = catalog[card][3]
    return sum(max(0, costs[i] - player['bonuses'][i] - player['tokens'][c])
               for i, c in enumerate(COLORS)) <= player['tokens']['gold']


def target(obs, action):
    if action['type'] in ('buy_market', 'reserve_market'):
        return obs['public']['market'][TIERS.index(action['tier'])][action['slot']]
    if action['type'] == 'buy_reserved':
        return next(x['card'] for x in obs['private']['reserved'] if x['slot'] == action['slot'])
    return None


def buyable(obs, actor, catalog):
    player = obs['public']['players'][actor]
    cards = [c for tier in obs['public']['market'] for c in tier if c is not None]
    cards += [x['card'] for x in obs['private']['reserved']]
    return [c for c in cards if affordable(c, player, catalog)]


def analyze_game(game, row, replay, old_profiles, catalog):
    actor = row['candidate_seat']; other = 1 - actor
    ranks = game['result']['ranks']
    half = 1 if ranks[actor] < ranks[other] else 0.5 if ranks[actor] == ranks[other] else 0
    own = next(x for x in game['players'] if x['actor'] == actor)
    profile = next(x for x in old_profiles if x['actor'] == actor)
    metrics = Counter(); events = []; reserved_at = {}; delays = []
    own_main = 0; bought = Counter(); unbought = {}
    for d in own['decisions']:
        obs, action = d['observation'], d['chosen_action']; typ = action['type']
        if typ == 'choose_noble':
            continue
        assert obs['public']['phase'] == 'main'
        own_main += 1
        player = obs['public']['players'][actor]; opponent = obs['public']['players'][other]
        purchasable = buyable(obs, actor, catalog)
        card = target(obs, action)
        if typ.startswith('buy_'):
            assert card in purchasable, ('recorded purchase not affordable', row['game_key'], own_main)
            bought[str(catalog[card][2])] += 1
        max_vp = max((catalog[c][2] for c in purchasable), default=-1)
        can_close = player['prestige'] + max_vp >= 15
        phase = 'early' if own_main <= 12 else 'middle' if own_main <= 20 else 'late'
        metrics['main_actions'] += 1; metrics[typ] += 1; metrics[f'{phase}_{typ}'] += 1
        metrics['any_buy_opportunities'] += bool(purchasable)
        metrics['score2_buy_opportunities'] += max_vp >= 2
        metrics['printed_close_opportunities'] += can_close
        metrics['nonbuy_with_score2'] += max_vp >= 2 and not typ.startswith('buy_')
        metrics['nonbuy_with_printed_close'] += can_close and not typ.startswith('buy_')
        metrics['opp12_decisions'] += opponent['prestige'] >= 12
        metrics['opp12_nonbuy'] += opponent['prestige'] >= 12 and not typ.startswith('buy_')
        if typ.startswith('reserve_'):
            metrics['reserve_with_any_buy'] += bool(purchasable)
            metrics['reserve_with_score2'] += max_vp >= 2
            metrics['reserve_with_printed_close'] += can_close
            metrics['reserve_opp12'] += opponent['prestige'] >= 12
            metrics['reserve_no_bank_gold'] += obs['public']['bank']['gold'] == 0
            metrics['reserve_already10tokens'] += sum(player['tokens'].values()) >= 10
            metrics['reserve_affordable_target'] += card is not None and card in purchasable
            if card is not None:
                metrics[f'reserve_vp{catalog[card][2]}'] += 1
                reserved_at[card] = own_main; unbought[card] = own_main
        if typ == 'buy_reserved':
            assert card in reserved_at
            delays.append(own_main - reserved_at[card]); unbought.pop(card, None)
        metrics['returned_tokens'] += sum(action.get('return', {}).values())
        event = dict(ply=d['ply'], own_main=own_main, action=action, card=card,
                     printed_vp=catalog[card][2] if card is not None else None,
                     vp=player['prestige'], opponent_vp=opponent['prestige'],
                     max_affordable_printed_vp=max_vp, affordable_cards=purchasable,
                     affordable_target=card in purchasable if card is not None else False,
                     end_game_triggered=obs['public']['end_game_triggered'])
        events.append(event)
    assert own_main == profile['main_actions']
    for key in ['take_tokens','buy_market','buy_reserved','reserve_market','reserve_deck','pass']:
        metrics.setdefault(key, 0)
    return {'game_key':row['game_key'],'model':row['game_key'].split('/')[0],
            'opponent':row['game_key'].split('/')[1], 'seed':row['seed'], 'seat':actor,
            'replay_sha256':row['replay_sha256'],'replay_path':row['source_path'],
            'score':half,'final_scores':game['result']['scores'],'metrics':dict(metrics),
            'purchased_by_vp':dict(bought),'reserve_purchase_delays':delays,
            'unbought_reserves':unbought,'first_big_main':profile['first_big_main'],
            'first_big_games':profile['first_big_games'], 'early_low_cards':profile['early_low_cards'],
            'early_discount_redemptions':profile['early_discount_redemptions'],
            'vp12':profile['own_main_12_vp'],'vp24':profile['own_main_24_vp'],
            'events':events, 'steps':replay['steps']}


def summarize(rows):
    n = len(rows); sums = Counter()
    for r in rows: sums.update(r['metrics'])
    output = {'games':n,'wdl':dict(Counter(str(r['score']) for r in rows)),
              'half_score':sum(r['score'] for r in rows)/n,
              'sum_metrics':dict(sums),'per_game':{k:v/n for k,v in sums.items()}}
    for k in ['vp12','vp24','first_big_main','early_low_cards','early_discount_redemptions']:
        vals=[r[k] for r in rows if r[k] is not None]
        output[k]={'mean':sum(vals)/len(vals) if vals else None,'n':len(vals)}
    delays=[v for r in rows for v in r['reserve_purchase_delays']]
    output['reserve_delay']={'mean':sum(delays)/len(delays) if delays else None,'n':len(delays)}
    output['conditional']={
        'reserve_given_any_buy':sums['reserve_with_any_buy']/sums['any_buy_opportunities'],
        'reserve_given_score2_buy':sums['reserve_with_score2']/sums['score2_buy_opportunities'],
        'nonbuy_given_printed_close':sums['nonbuy_with_printed_close']/sums['printed_close_opportunities'],
        'reserve_given_opp12':sums['reserve_opp12']/sums['opp12_decisions']}
    return output


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.root;out=args.out;out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(root))
    from training.prism_portable.engine.ppo.building import CARD_CATALOG
    cache_path=root/'local-artifacts/prism/m79-mainline/completion-r37/m79-candidate-profile.verified-input-cache.json'
    projector=root/'local-artifacts/prism/m79-mainline/completion-r36/prism_building_projection'
    result_path=root/'benchmarks/m79-prism-mainline.result.json'
    assert digest(cache_path)==CACHE_SHA;assert digest(projector)==PROJECTOR_SHA;assert digest(result_path)==RESULT_SHA
    cache=json.loads(cache_path.read_text()); frozen=json.loads(result_path.read_text())
    rows=[r for r in cache['profile_receipt']['replays'] if r['game_key'].split('/')[0] in ['a','base'] and r['game_key'].split('/')[1] in ['heuristic','balance']]
    assert len(rows)==2048
    results=[];batches=[];panel_checks=0;start=time.time()
    with tempfile.TemporaryDirectory(prefix='m79-regression-replays-') as tmp:
        stage=Path(tmp)
        for first in range(0,len(rows),64):
            batch=rows[first:first+64];m=stage/'manifest.json';p=stage/'projection.json';panel=stage/'panel.jsonl'
            m.write_text(json.dumps([{'replay_path':r['source_path'],'replay_sha256':r['replay_sha256']} for r in batch]))
            # Existing projector also provides authoritative legal actions on Main4/8/12.
            command=[str(projector),str(m),str(p),'--panel-max-games','64','--panel-output',str(panel)]
            if p.exists(): p.unlink()
            if panel.exists(): panel.unlink()
            proc=subprocess.run(command,capture_output=True,text=True,timeout=120)
            assert proc.returncode==0,proc.stderr
            games=json.loads(p.read_text())['games'];assert len(games)==len(batch)
            for line in panel.read_text().splitlines():
                pr=json.loads(line);obs=pr['observation'];actor=pr['actor']
                rust_cards={target(obs,a) for a in pr['legal_actions'] if a['type'].startswith('buy_')}
                assert rust_cards==set(buyable(obs,actor,CARD_CATALOG))
                panel_checks+=1
            for g,row in zip(games,batch):
                assert g['replay_sha256']==row['replay_sha256'] and g['terminal'] and g['seed']==row['seed']
                rp=Path(row['source_path']);assert digest(rp)==row['replay_sha256']
                replay=json.loads(rp.read_text())
                results.append(analyze_game(g,row,replay,cache['profiles_by_game'][row['game_key']],CARD_CATALOG))
            batches.append({'first':first,'games':len(batch),'manifest_sha256':digest(m),'projection_sha256':digest(p),'legal_panel_sha256':digest(panel)})
            print(json.dumps({'processed':len(results),'total':len(rows),'wall_seconds':round(time.time()-start,1)}),flush=True)
    summary={};transitions={};diffs=[]
    keyed={(r['model'],r['opponent'],r['seed'],r['seat']):r for r in results}
    for opponent in ['heuristic','balance']:
        for model in ['base','a']:
            group=[r for r in results if r['opponent']==opponent and r['model']==model]
            assert len(group)==512
            old=next(p['candidate_metrics'] for p in frozen['pairs'] if p['candidate']==model and p['opponent']==opponent)
            agg=summarize(group);assert abs(agg['half_score']-old['score_rate'])<1e-12
            for k in ['buy_market','buy_reserved','take_tokens','reserve_market','reserve_deck','pass']:
                assert agg['sum_metrics'][k]==old['action_distribution'][k]
            summary[f'{model}/{opponent}']=agg
        for b in [r for r in results if r['opponent']==opponent and r['model']=='base']:
            a=keyed['a',opponent,b['seed'],b['seat']]
            divergence=None
            for sa,sb in zip(a['steps'],b['steps']):
                assert sa['state_hash_before']==sb['state_hash_before']
                if sa['action']!=sb['action']:
                    assert sa['actor']==sb['actor']==a['seat'], 'deterministic opponent diverged before candidate'
                    ea=next(x for x in a['events'] if x['ply']==sa['ply']);eb=next(x for x in b['events'] if x['ply']==sb['ply'])
                    assert ea['affordable_cards']==eb['affordable_cards']
                    divergence={'ply':sa['ply'],'state_hash':sa['state_hash_before'],'a':ea,'base':eb}
                    break
            diffs.append({'opponent':opponent,'seed':a['seed'],'seat':a['seat'],'base_score':b['score'],'a_score':a['score'],
                          'delta':a['score']-b['score'],'first_divergence':divergence,'base_key':b['game_key'],'a_key':a['game_key']})
        ds=[d for d in diffs if d['opponent']==opponent]
        transitions[opponent]=dict(Counter(f"{d['base_score']}->{d['a_score']}" for d in ds))
    for r in results:r.pop('steps')
    payload={'format':'m79-existing-replay-regression-diagnostic-v1','new_games':0,'model_forwards':0,'coverage':2048,
             'result_sha256':RESULT_SHA,'cache_sha256':CACHE_SHA,'projector_sha256':PROJECTOR_SHA,
             'script_sha256':digest(Path(__file__)),'catalog_source_sha256':digest(root/'training/prism_portable/engine/ppo/building.py'),
             'wall_seconds':time.time()-start,'affordability_rust_panel_checks':panel_checks,
             'scope':'posthoc descriptive diagnosis; no counterfactual rollout and no causal estimate of reserve penalty',
             'summary':summary,'transitions':transitions,'paired_games':diffs,'games':results,'batches':batches}
    p=out/'diagnostic.json';p.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')))
    assert digest(result_path)==RESULT_SHA
    print(json.dumps({'status':'PASS','output':str(p),'sha256':digest(p),'bytes':p.stat().st_size,'coverage':2048,'panel_checks':panel_checks}),flush=True)


if __name__=='__main__':main()
