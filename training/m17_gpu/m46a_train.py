"""M46A frozen training + evaluation (exact DESIGN V2 recipe).

Frozen recipe:
  training seed   = 46_000_001
  optimizer       = AdamW(lr=3e-4, weight_decay=1e-4, betas=(0.9,0.999), eps=1e-8)
  epochs          = 32
  batch unit      = root, batch size = 32 roots (4 consecutive games per batch)
  grad clip       = global norm 1.0
  dropout         = 0
  scheduler       = cosine annealing over 32 epochs, 3e-4 -> 3e-5
  init            = framework default uniform under the training seed;
                    LayerNorm weight=1, bias=0
  loss            = L_progress + L_rank + 0.5 * L_mechanics
    L_progress: SmoothL1(beta=1.0) model P(nonterminal successor, player)
                vs teacher_progress/1e8, mean over scored examples
    L_rank:     pairwise logistic over teacher strict action pairs per root
                on mean model scores; per-root pair mean, then batch mean
    L_mechanics: mean of 4 classification CEs (card heads: all nonterminal
                examples; noble heads: has_nobles examples only)

Checkpoint selection: all 32 epochs; highest val optimal-set agreement ->
tie highest val strict-pair accuracy -> tie lowest val regret ->
tie earliest epoch. The selected checkpoint is evaluated once on test and
once on unseen SHIFT1 pairs. No test-driven reselection.

Outputs (local-artifacts/m46a-run/):
  best.pt, epoch_metrics.json, test_eval.npz, shift1_eval.npz,
  final_metrics.json (PASS/FAIL per frozen gate).
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS = REPO / "local-artifacts/m46a-corpus"
RUN_DIR = REPO / "local-artifacts/m46a-run"

TRAIN_SEED = 46_000_001
LR, WD, BETAS, EPS = 3e-4, 1e-4, (0.9, 0.999), 1e-8
EPOCHS, BATCH_ROOTS, CLIP, ETA_MIN = 32, 32, 1.0, 3e-5
BETA_SMOOTHL1 = 1.0
PROGRESS_SCALE = 100_000_000.0
N_DETS, N_PLAYERS = 4, 2

SPLITS = {"train": (6_600_000, 6_602_047), "val": (6_602_048, 6_602_303),
          "test": (6_602_304, 6_602_559)}


def set_deterministic():
    torch.manual_seed(TRAIN_SEED)
    np.random.seed(TRAIN_SEED % (2 ** 32))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


LOAD_KEYS = ("card", "noble", "praw", "glob", "n_actions", "terminal",
             "teacher_util", "progress", "mech", "has_nobles",
             "n_cards", "n_nobles", "root_meta")


def shift1(b):
    b = np.asarray(b)
    return b[..., [4, 0, 1, 2, 3]]


class ShardStore:
    """Loads per-game NPZ shards; preloads val/test, streams train."""

    def __init__(self, split, preload):
        a, b = SPLITS[split]
        self.paths = [CORPUS / "games" / split / f"seed-{s}" / "shard.npz"
                      for s in range(a, b + 1)]
        for p in self.paths:
            if not p.exists():
                raise RuntimeError(f"missing shard {p}")
        self.cache = {}
        if preload:
            for p in self.paths:
                self.cache[str(p)] = dict(np.load(p, allow_pickle=False))

    def get(self, path, keys=None):
        key = str(path)
        if key in self.cache:
            z = self.cache[key]
            return z if keys is None else {k: z[k] for k in keys}
        zf = np.load(path, allow_pickle=False)
        if keys is None:
            return dict(zf)
        return {k: zf[k] for k in keys}


def build_inputs(z, ri, ai, si, pi, shifted=False):
    """Build model input tensors for one scoring example (numpy float32)."""
    n_cards = int(z["n_cards"][ri, ai, si, pi])
    n_nobles = int(z["n_nobles"][ri, ai, si, pi])
    praw = z["praw"][ri, ai, si, pi].astype(np.int64)  # 26
    bonuses = praw[1:6].copy()
    tokens = praw[6:11].copy()
    gold = int(praw[11])
    if shifted:
        bonuses = shift1(bonuses)
    card_rows = []
    for ci in range(n_cards):
        c = z["card"][ri, ai, si, pi, ci].astype(np.int64)
        cost, prestige, tier, bonus, role = c[0:5], int(c[5]), int(c[6]), int(c[7]), int(c[8])
        disc = np.maximum(cost - bonuses, 0)
        short = np.maximum(disc - tokens, 0)
        gn = int(short.sum())
        aff = 1 if gold >= gn else 0
        tier_oh = np.zeros(3)
        tier_oh[tier] = 1
        bonus_oh = np.zeros(5)
        bonus_oh[bonus] = 1
        role_oh = np.zeros(2)
        role_oh[role] = 1
        tok6 = np.append(tokens, gold)
        card_rows.append(np.concatenate([
            cost, [prestige], tier_oh, bonus_oh, role_oh,
            bonuses, tok6, disc, short, [gn, aff]]).astype(np.float32))
    noble_rows = []
    for ni in range(n_nobles):
        nb = z["noble"][ri, ai, si, pi, ni].astype(np.int64)
        req, nprest = nb[0:5], int(nb[5])
        deficit = np.maximum(req - bonuses, 0)
        claim = 1 if deficit.sum() == 0 else 0
        noble_rows.append(np.concatenate(
            [req, [nprest], deficit, [claim]]).astype(np.float32))
    praw_f = praw.astype(np.float32)
    if shifted:
        praw_f[1:6] = shift1(praw[1:6])
    glob = z["glob"][ri, ai, si, pi].astype(np.float32)
    return card_rows, noble_rows, praw_f, glob


def shard_to_examples(z, ri_list, shifted=False, for_train=True):
    """Flatten (root, action, det, player) scoring examples to padded tensors."""
    import torch as T
    ex = []
    for ri in ri_list:
        na = int(z["n_actions"][ri])
        for ai in range(na):
            for si in range(N_DETS):
                term = bool(z["terminal"][ri, ai, si])
                for pi in range(N_PLAYERS):
                    cards, nobles, praw, glob = build_inputs(z, ri, ai, si, pi, shifted)
                    ex.append(dict(ri=ri, ai=ai, si=si, pi=pi, terminal=term,
                                   cards=cards, nobles=nobles, praw=praw, glob=glob,
                                   tu=int(z["teacher_util"][ri, ai, si, pi]),
                                   tvec=[int(x) for x in z["teacher_util"][ri, ai, si]],
                                   prog=int(z["progress"][ri, ai, si, pi]),
                                   mech=z["mech"][ri, ai, si, pi].astype(np.int64),
                                   has_nb=bool(z["has_nobles"][ri, ai, si, pi])))
    if not ex:
        return None
    nc = max(len(e["cards"]) for e in ex)
    nn = max(len(e["nobles"]) for e in ex)
    B = len(ex)
    card = np.zeros((B, nc, 39), np.float32)
    cmask = np.zeros((B, nc), bool)
    noble = np.zeros((B, nn, 12), np.float32)
    nmask = np.zeros((B, nn), bool)
    praw = np.zeros((B, 26), np.float32)
    glob = np.zeros((B, 13), np.float32)
    for i, e in enumerate(ex):
        if e["cards"]:
            card[i, :len(e["cards"])] = np.stack(e["cards"])
            cmask[i, :len(e["cards"])] = True
        if e["nobles"]:
            noble[i, :len(e["nobles"])] = np.stack(e["nobles"])
            nmask[i, :len(e["nobles"])] = True
        praw[i] = e["praw"]
        glob[i] = e["glob"]
    return {"ex": ex, "card": card, "cmask": cmask, "noble": noble, "nmask": nmask,
            "praw": praw, "glob": glob}


@torch.no_grad()
def score_examples(model, tensors, device):
    from splendor_gpu.m46a_model import RelationalSuccessorScorer  # noqa
    d = {k: (torch.from_numpy(v).to(device) if isinstance(v, np.ndarray) else v)
         for k, v in tensors.items() if k in ("card", "noble", "praw", "glob")}
    d["card_mask"] = torch.from_numpy(tensors["cmask"]).to(device)
    d["noble_mask"] = torch.from_numpy(tensors["nmask"]).to(device)
    out = model.encode(d["card"], d["card_mask"], d["noble"], d["noble_mask"],
                       d["praw"], d["glob"])
    return {k: (v.detach().cpu() if isinstance(v, torch.Tensor) else v)
            for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    args = ap.parse_args()
    set_deterministic()
    device = torch.device(args.device)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    from splendor_gpu.m46a_model import RelationalSuccessorScorer
    model = RelationalSuccessorScorer().to(device)

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD,
                            betas=BETAS, eps=EPS)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs,
                                                       eta_min=ETA_MIN)

    train_store = ShardStore("train", preload=False)
    val_store = ShardStore("val", preload=True)
    n_train_games = len(train_store.paths)

    def game_roots(split_store):
        # list of (path_idx, root_idx)
        idx = []
        for gi in range(len(split_store.paths)):
            for ri in range(8):
                idx.append((gi, ri))
        return idx

    train_index = game_roots(train_store)
    val_index = game_roots(val_store)

    def load_batch(items, store):
        # items: list of (gi, ri); returns padded batch tensors, flat metas,
        # and per-root boundary records (start/count/n_actions/actor/teacher).
        per_shard = {}
        for gi, ri in items:
            p = (train_store.paths[gi] if store is train_store else val_store.paths[gi])
            per_shard.setdefault(str(p), []).append(ri)
        parts, metas, root_bounds = [], [], []
        for key, ris in per_shard.items():
            zpath = Path(key)
            z = (train_store.get(zpath, LOAD_KEYS) if store is train_store
                 else val_store.get(zpath, LOAD_KEYS))
            t = shard_to_examples(z, ris)
            base = len(metas)
            for ri in ris:
                na = int(z["n_actions"][ri])
                actor = int(z["root_meta"][ri][2])
                q = [float(z["teacher_util"][ri, ai, :, actor].mean())
                     for ai in range(na)]
                root_bounds.append({
                    "start": base, "count": na * N_DETS * N_PLAYERS,
                    "n_actions": na, "actor": actor, "opp": 1 - actor,
                    "teacher_means": q,
                })
                base += na * N_DETS * N_PLAYERS
            parts.append(t)
            metas.extend(t["ex"])
        # concat
        cat = {}
        for k in ("card", "noble", "praw", "glob"):
            m = max(p[k].shape[1] for p in parts)
            arrs = []
            for p in parts:
                pad = m - p[k].shape[1]
                if pad:
                    arrs.append(np.pad(p[k], ((0, 0), (0, pad), (0, 0))))
                else:
                    arrs.append(p[k])
            cat[k] = np.concatenate(arrs, axis=0)
        for k in ("cmask", "nmask"):
            m = max(p[k].shape[1] for p in parts)
            arrs = [np.pad(p[k], ((0, 0), (0, m - p[k].shape[1]))) for p in parts]
            cat[k] = np.concatenate(arrs, axis=0)
        return cat, metas, root_bounds

    def forward_batch(cat):
        t = {k: torch.from_numpy(v).to(device) for k, v in cat.items()
             if k in ("card", "noble", "praw", "glob")}
        t["cmask"] = torch.from_numpy(cat["cmask"]).to(device)
        t["nmask"] = torch.from_numpy(cat["nmask"]).to(device)
        return model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                            t["praw"], t["glob"])

    history = []
    best = None  # (agree, pair_acc, -regret, -epoch)
    best_epoch = -1
    n_batches = math.ceil(len(train_index) / BATCH_ROOTS)

    for epoch in range(args.epochs):
        model.train()
        g = torch.Generator().manual_seed(TRAIN_SEED + epoch)
        # permute games, take 4 consecutive games (32 roots) per batch
        gperm = torch.randperm(n_train_games, generator=g).tolist()
        batches = [gperm[i:i + 4] for i in range(0, n_train_games, 4)]
        tot_loss = 0.0
        nb = 0
        for b_games in batches:
            items = [(gi, ri) for gi in b_games for ri in range(8)]
            cat, metas, root_bounds = load_batch(items, train_store)
            out = forward_batch(cat)
            B = len(metas)
            prog_t = torch.tensor([e["prog"] / PROGRESS_SCALE for e in metas],
                                  dtype=torch.float32, device=device)
            term_m = torch.tensor([e["terminal"] for e in metas], device=device)
            learn_m = ~term_m
            if learn_m.any():
                l_prog = F.smooth_l1_loss(out["progress"][learn_m], prog_t[learn_m],
                                          beta=BETA_SMOOTHL1)
            else:
                l_prog = torch.zeros((), device=device)
            # mechanics
            ce_terms = []
            aff_c = torch.tensor([e["mech"][0] for e in metas], device=device)
            aff_m = torch.tensor([e["mech"][1] for e in metas], device=device)
            clm = torch.tensor([e["mech"][2] for e in metas], device=device)
            mnd = torch.tensor([e["mech"][3] for e in metas], device=device)
            has_nb = torch.tensor([e["has_nb"] for e in metas], device=device)
            if learn_m.any():
                ce_terms.append(F.cross_entropy(out["aff_count"][learn_m], aff_c[learn_m]))
                ce_terms.append(F.cross_entropy(out["aff_max"][learn_m], aff_m[learn_m]))
            else:
                ce_terms += [torch.zeros((), device=device)] * 2
            nbm = learn_m & has_nb
            if nbm.any():
                ce_terms.append(F.cross_entropy(out["noble_claim"][nbm], clm[nbm]))
                ce_terms.append(F.cross_entropy(out["noble_mindef"][nbm], mnd[nbm]))
            else:
                ce_terms += [torch.zeros((), device=device)] * 2
            l_mech = sum(ce_terms) / 4
            # rank: pairwise logistic over teacher strict pairs per root on
            # mean model scores; per-root pair mean, then batch mean over
            # roots that have at least one strict pair.
            prog_flat = out["progress"]
            l_rank_terms = []
            for rb in root_bounds:
                na, actor, opp = rb["n_actions"], rb["actor"], rb["opp"]
                q = rb["teacher_means"]
                mns = []
                for ai in range(na):
                    s = torch.zeros((), device=device)
                    for si in range(N_DETS):
                        b = rb["start"] + ((ai * N_DETS) + si) * N_PLAYERS
                        er = metas[b + (0 if actor == 0 else 1)]
                        if er["terminal"]:
                            s = s + er["tu"]
                        else:
                            s = s + (prog_flat[b + (0 if actor == 0 else 1)]
                                     - prog_flat[b + (0 if opp == 0 else 1)])
                    mns.append(s / N_DETS)
                pair_losses = []
                for i in range(na):
                    for j in range(na):
                        if i == j or q[i] == q[j]:
                            continue
                        sgn = 1.0 if q[i] > q[j] else -1.0
                        pair_losses.append(F.softplus(-sgn * (mns[i] - mns[j])))
                if pair_losses:
                    l_rank_terms.append(sum(pair_losses) / len(pair_losses))
            if l_rank_terms:
                l_rank = sum(l_rank_terms) / len(l_rank_terms)
            else:
                l_rank = torch.zeros((), device=device)
            loss = l_prog + l_rank + 0.5 * l_mech
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            opt.step()
            tot_loss += loss.item()
            nb += 1
        sched.step()
        # validation
        val_metrics = evaluate_split(model, val_store, val_index, device)
        agree, pacc, regret = (val_metrics["optimal_set_agreement"],
                              val_metrics["strict_pair_accuracy"],
                              val_metrics["mean_regret"])
        key = (round(agree, 12), round(pacc, 12), round(-regret, 12), -epoch)
        improved = best is None or key > best
        if improved:
            best = key
            best_epoch = epoch
            torch.save(model.state_dict(), RUN_DIR / "best.pt")
        torch.save(model.state_dict(), RUN_DIR / f"epoch-{epoch:02d}.pt")
        history.append({"epoch": epoch, "train_loss": tot_loss / max(nb, 1),
                        **{f"val_{k}": v for k, v in val_metrics.items()
                           if isinstance(v, float)},
                        "best_epoch": best_epoch})
        print(f"epoch {epoch:02d} loss={tot_loss/max(nb,1):.4f} "
              f"val_agree={agree:.4f} val_pair={pacc:.4f} val_regret={regret:.5f} "
              f"best={best_epoch}", flush=True)

    (RUN_DIR / "epoch_metrics.json").write_text(json.dumps(history, indent=2))
    print(f"BEST EPOCH: {best_epoch}")
    # reload best and final eval
    model.load_state_dict(torch.load(RUN_DIR / "best.pt", map_location=device))
    test_store = ShardStore("test", preload=True)
    test_index = game_roots(test_store)
    test_metrics = evaluate_split(model, test_store, test_index, device,
                                  save_prefix="test")
    print("TEST:", json.dumps({k: v for k, v in test_metrics.items()
                               if isinstance(v, float)}, indent=2))
    shift_metrics = evaluate_shift1(model, test_store, test_index, device)
    print("SHIFT1:", json.dumps(shift_metrics, indent=2))
    final = {"best_epoch": best_epoch, "test": test_metrics, "shift1": shift_metrics,
             "history": history}
    (RUN_DIR / "final_metrics.json").write_text(json.dumps(final, indent=2,
                                                           default=_json_default))
    # PASS/FAIL verdict
    verdict = compute_verdict(final)
    print("VERDICT:", verdict)
    (RUN_DIR / "verdict.json").write_text(json.dumps(verdict, indent=2))
    if verdict["overall"] != "PASS":
        raise SystemExit(f"M46A VALID RUN FAIL: {verdict['failed_gates']}")


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(repr(o))


def evaluate_split(model, store, index, device, save_prefix=None):
    """Gate A (mechanics on test examples) + Gate B (ranking per root)."""
    model.eval()
    # group index by shard
    per_shard = {}
    for gi, ri in index:
        per_shard.setdefault(gi, []).append(ri)
    # Gate A accumulators
    aff_c_ok = aff_c_n = aff_m_ok = aff_m_n = 0
    clm_ok = clm_n = mnd_ok = mnd_n = 0
    save_pred = [] if save_prefix else None
    # Gate B accumulators
    roots_total = 0
    opt_ok = 0
    sp_ok = sp_n = 0
    regrets = []
    zero_regret = 0
    saved_roots = []  # (teacher_means, model_means) per root for audit
    with torch.no_grad():
        for gi, ris in per_shard.items():
            z = store.get(store.paths[gi])
            t = shard_to_examples(z, ris)
            out = score_examples(model, t, device)
            prog = out["progress"].numpy()
            # Gate A per example
            for i, e in enumerate(t["ex"]):
                if e["terminal"]:
                    continue
                pa = (int(np.argmax(out["aff_count"][i].numpy())),
                      int(np.argmax(out["aff_max"][i].numpy())),
                      int(np.argmax(out["noble_claim"][i].numpy())),
                      int(np.argmax(out["noble_mindef"][i].numpy())))
                lt = (e["mech"][0], e["mech"][1], e["mech"][2], e["mech"][3])
                if save_pred is not None:
                    save_pred.append(pa + lt + (int(e["has_nb"]),))
                if pa[0] == lt[0]:
                    aff_c_ok += 1
                aff_c_n += 1
                if pa[1] == lt[1]:
                    aff_m_ok += 1
                aff_m_n += 1
                if e["has_nb"]:
                    if pa[2] == lt[2]:
                        clm_ok += 1
                    clm_n += 1
                    if pa[3] == lt[3]:
                        mnd_ok += 1
                    mnd_n += 1
            # Gate B per root: means over dets; terminal bypass uses exact teacher
            # rebuild per-root structure from ex list order
            pos = 0
            for ri in ris:
                na = int(z["n_actions"][ri])
                actor = int(z["root_meta"][ri][2])
                opp = 1 - actor
                q, m = [], []
                for ai in range(na):
                    tq = mm = 0.0
                    for si in range(N_DETS):
                        # find example indices: order is ri,ai,si,pi
                        base = pos + ((ai * N_DETS) + si) * N_PLAYERS
                        er = t["ex"][base + (0 if actor == 0 else 1)]
                        tq += er["tvec"][actor] / N_DETS
                        if er["terminal"]:
                            mm += er["tvec"][actor] / N_DETS
                        else:
                            mm += (prog[base + (0 if actor == 0 else 1)]
                                   - prog[base + (0 if opp == 0 else 1)]) / N_DETS
                    q.append(tq)
                    m.append(mm)
                pos += na * N_DETS * N_PLAYERS
                q = np.array(q, dtype=np.float64)
                m = np.array(m, dtype=np.float64)
                roots_total += 1
                best = q.max()
                astar = set(np.flatnonzero(q == best).tolist())
                mhat = int(np.argmax(m))
                if mhat in astar:
                    opt_ok += 1
                for i in range(na):
                    for j in range(na):
                        if i == j or q[i] == q[j]:
                            continue
                        sp_n += 1
                        if np.sign(m[i] - m[j]) == np.sign(q[i] - q[j]) and m[i] != m[j]:
                            sp_ok += 1
                rstar = float(q[np.argmax(q)])
                rhat = float(q[mhat])
                denom = max(rstar - float(q.min()), 1.0)
                r = (rstar - rhat) / denom
                regrets.append(r)
                if r == 0.0:
                    zero_regret += 1
                if save_prefix:
                    saved_roots.append({"teacher_means": q.tolist(), "model_means": m.tolist()})
    regrets = np.array(regrets)
    out = {
        "aff_count_acc": aff_c_ok / aff_c_n if aff_c_n else 0.0,
        "aff_max_acc": aff_m_ok / aff_m_n if aff_m_n else 0.0,
        "claim_acc": clm_ok / clm_n if clm_n else 0.0,
        "mindef_acc": mnd_ok / mnd_n if mnd_n else 0.0,
        "optimal_set_agreement": opt_ok / roots_total,
        "strict_pair_accuracy": sp_ok / sp_n if sp_n else 0.0,
        "mean_regret": float(regrets.mean()),
        "zero_regret_rate": zero_regret / roots_total,
        "regret_p50": float(np.percentile(regrets, 50)),
        "regret_p90": float(np.percentile(regrets, 90)),
        "regret_p95": float(np.percentile(regrets, 95)),
        "regret_max": float(regrets.max()),
        "roots": roots_total,
        "strict_pairs": sp_n,
    }
    if save_prefix:
        np.savez_compressed(RUN_DIR / f"{save_prefix}_gateb_roots.npz",
                            **{f"root_{i}": np.array([r["teacher_means"], r["model_means"]])
                               for i, r in enumerate(saved_roots)})
        np.savez_compressed(RUN_DIR / f"{save_prefix}_gatea_preds.npz",
                            preds=np.array(save_pred, dtype=np.int64))
    return out


def evaluate_shift1(model, store, index, device):
    """Unseen SHIFT1 paired sensitivity on frozen test successors."""
    model.eval()
    per_shard = {}
    for gi, ri in index:
        per_shard.setdefault(gi, []).append(ri)
    # targets: aff_count, aff_max, claim, mindef
    stats = {k: {"changed": 0, "both_ok": 0, "sign_ok": 0} for k in
             ("aff_count", "aff_max", "claim", "mindef")}
    save_rows = []
    with torch.no_grad():
        for gi, ris in per_shard.items():
            z = store.get(store.paths[gi])
            t = shard_to_examples(z, ris)
            out_t = score_examples(model, t, device)
            ts = shard_to_examples(z, ris, shifted=True)
            out_s = score_examples(model, ts, device)
            heads = [("aff_count", out_t["aff_count"], out_s["aff_count"]),
                     ("aff_max", out_t["aff_max"], out_s["aff_max"]),
                     ("claim", out_t["noble_claim"], out_s["noble_claim"]),
                     ("mindef", out_t["noble_mindef"], out_s["noble_mindef"])]
            for i, e in enumerate(t["ex"]):
                if e["terminal"]:
                    continue
                lt = [e["mech"][0], e["mech"][1], e["mech"][2], e["mech"][3]]
                ls = shifted_labels(z, t, i, e)
                noble_ok = e["has_nb"]
                pt_all = [int(np.argmax(out_t["aff_count"][i].numpy())),
                          int(np.argmax(out_t["aff_max"][i].numpy())),
                          int(np.argmax(out_t["noble_claim"][i].numpy())),
                          int(np.argmax(out_t["noble_mindef"][i].numpy()))]
                ps_all = [int(np.argmax(out_s["aff_count"][i].numpy())),
                          int(np.argmax(out_s["aff_max"][i].numpy())),
                          int(np.argmax(out_s["noble_claim"][i].numpy())),
                          int(np.argmax(out_s["noble_mindef"][i].numpy()))]
                save_rows.append(pt_all + ps_all + lt + ls + [int(noble_ok)])
                for (name, pt, ps), ltv, lsv in zip(heads, lt, ls):
                    if name in ("claim", "mindef") and not noble_ok:
                        continue
                    if ltv == lsv:
                        continue
                    st = stats[name]
                    st["changed"] += 1
                    pt_i = int(np.argmax(pt[i].numpy()))
                    ps_i = int(np.argmax(ps[i].numpy()))
                    if pt_i == ltv and ps_i == lsv:
                        st["both_ok"] += 1
                    if np.sign(ps_i - pt_i) == np.sign(lsv - ltv):
                        st["sign_ok"] += 1
    np.savez_compressed(RUN_DIR / "shift1_preds.npz",
                        rows=np.array(save_rows, dtype=np.int64))
    res = {}
    for k, st in stats.items():
        n = st["changed"]
        res[k] = {"changed_pairs": n,
                  "both_side_exact": st["both_ok"] / n if n else 0.0,
                  "signed_delta_acc": st["sign_ok"] / n if n else 0.0}
    return res


def shifted_labels(z, t, i, e):
    """Recompute mechanics labels under SHIFT1 from stored raw fields."""
    # e carries no raw card/noble rows; recompute from shard arrays via indices
    # stored in the example dict during shard_to_examples? We rebuild here from
    # the flat tensors: card rows for this example are in t['card'][i].
    # Bonus vector lives in praw; shift it and recompute.
    import numpy as _np
    praw = t["praw"][i].astype(_np.int64)
    b = shift1(praw[1:6])
    tok = praw[6:11]
    gold = int(praw[11])
    cards = t["card"][i]  # (C,39) float
    cmask = t["cmask"][i]
    aff = mp = 0
    for ci in range(cards.shape[0]):
        if not cmask[ci]:
            continue
        row = cards[ci].astype(_np.int64)
        cost = row[0:5]
        pres = int(row[5])
        disc = _np.maximum(cost - b, 0)
        short = _np.maximum(disc - tok, 0)
        if gold >= int(short.sum()):
            aff += 1
            mp = max(mp, pres)
    nobles = t["noble"][i]
    nmask = t["nmask"][i]
    claim = 0
    mnd = None
    for ni in range(nobles.shape[0]):
        if not nmask[ni]:
            continue
        row = nobles[ni].astype(_np.int64)
        req = row[0:5]
        d = _np.maximum(req - b, 0)
        tot = int(d.sum())
        if tot == 0:
            claim += 1
        mnd = tot if mnd is None else min(mnd, tot)
    return [aff, mp, claim, mnd if mnd is not None else -1]


def compute_verdict(final):
    t = final["test"]
    s = final["shift1"]
    failed = []

    def chk(name, ok):
        if not ok:
            failed.append(name)

    chk("A2-affordable-count", t["aff_count_acc"] >= 0.995)
    chk("A2-max-prestige", t["aff_max_acc"] >= 0.995)
    chk("A2-claimable", t["claim_acc"] >= 0.995)
    chk("A2-min-deficit", t["mindef_acc"] >= 0.99)
    for k in ("aff_count", "aff_max", "claim", "mindef"):
        if s[k]["changed_pairs"] < 256:
            failed.append(f"A3-coverage-{k}")
    for k in ("aff_count", "aff_max", "claim", "mindef"):
        chk(f"A3-both-exact-{k}", s[k]["both_side_exact"] >= 0.99)
        chk(f"A3-signed-delta-{k}", s[k]["signed_delta_acc"] >= 0.99)
    chk("B1-optimal-set", t["optimal_set_agreement"] >= 0.98)
    chk("B1-strict-pair", t["strict_pair_accuracy"] >= 0.99)
    chk("B1-regret", t["mean_regret"] <= 0.005)
    return {"overall": "PASS" if not failed else "FAIL", "failed_gates": failed}


if __name__ == "__main__":
    main()
