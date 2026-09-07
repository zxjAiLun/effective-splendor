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


def root_tensors(z, ri, shifted=False):
    """Vectorized model inputs + labels for all (action, det, player) of a root.

    Array shapes carry (A, D, P, ...) with A = n_actions[ri]. All rules are
    identical to the per-example path; only the loop order is eliminated.
    """
    na = int(z["n_actions"][ri])
    card = z["card"][ri, :na].astype(np.int64)      # (A,D,P,15,21)
    nc = z["n_cards"][ri, :na]                       # (A,D,P)
    noble = z["noble"][ri, :na].astype(np.int64)     # (A,D,P,5,12)
    nnb = z["n_nobles"][ri, :na]                     # (A,D,P)
    praw_i = z["praw"][ri, :na].astype(np.int64)     # (A,D,P,26)
    glob = z["glob"][ri, :na].astype(np.float32)     # (A,D,P,13)
    term = z["terminal"][ri, :na]                    # (A,D)
    tu = z["teacher_util"][ri, :na].astype(np.int64)  # (A,D,2)
    prog = z["progress"][ri, :na].astype(np.int64)    # (A,D,2)
    mech = z["mech"][ri, :na].astype(np.int64)        # (A,D,P,4)
    has_nb = z["has_nobles"][ri, :na]                # (A,D,P)
    actor = int(z["root_meta"][ri][2])
    bonuses = praw_i[..., 1:6].copy()
    if shifted:
        bonuses = shift1(bonuses)
    tokens = praw_i[..., 6:11]
    gold = praw_i[..., 11:12]
    cost = card[..., 0:5]
    pres = card[..., 5:6].astype(np.float32)
    Bb = bonuses[..., None, :]
    disc = np.maximum(cost - Bb, 0)
    short = np.maximum(disc - tokens[..., None, :], 0)
    gn = short.sum(axis=-1, keepdims=True)
    aff = (gold[..., None, :] >= gn).astype(np.float32)
    tier_oh = (card[..., 6:7] == np.arange(3)).astype(np.float32)
    bonus_oh = (card[..., 7:8] == np.arange(5)).astype(np.float32)
    role_oh = (card[..., 8:9] == np.arange(2)).astype(np.float32)
    tok6 = np.concatenate([np.broadcast_to(tokens[..., None, :], disc.shape),
                           np.broadcast_to(gold[..., None, :], gn.shape)], axis=-1)
    card39 = np.concatenate([
        cost.astype(np.float32), pres, tier_oh, bonus_oh, role_oh,
        np.broadcast_to(bonuses[..., None, :], disc.shape).astype(np.float32),
        tok6.astype(np.float32), disc.astype(np.float32),
        short.astype(np.float32), gn.astype(np.float32), aff], axis=-1)
    cmask = np.arange(15).reshape(1, 1, 1, 15) < nc[..., None]
    req = noble[..., 0:5]
    npres = noble[..., 5:6].astype(np.float32)
    deficit = np.maximum(req - bonuses[..., None, :], 0)
    claim = (deficit.sum(axis=-1, keepdims=True) == 0).astype(np.float32)
    noble12 = np.concatenate([req.astype(np.float32), npres,
                              deficit.astype(np.float32), claim], axis=-1)
    nmask = np.arange(5).reshape(1, 1, 1, 5) < nnb[..., None]
    praw_f = praw_i.astype(np.float32)
    praw_f[..., 1:6] = bonuses
    # mechanics labels recomputed (must equal stored labels when not shifted)
    aff_c = ((aff[..., 0] > 0) & cmask).sum(axis=-1)
    best = np.where(cmask & (aff[..., 0] > 0), card[..., 5], -1)
    maxp = np.maximum(best.max(axis=-1), 0)
    dtot = deficit.sum(axis=-1)
    clm = ((dtot == 0) & nmask).sum(axis=-1)
    any_nb = nmask.any(axis=-1)
    mnd = np.where(any_nb, np.where(nmask, dtot, 10 ** 9).min(axis=-1), -1)
    return {
        "na": na, "actor": actor, "opp": 1 - actor,
        "card39": card39, "cmask": cmask, "noble12": noble12,
        "nmask": nmask, "praw": praw_f, "glob": glob,
        "term": term, "tu": tu, "prog": prog, "mech": mech,
        "has_nb": has_nb, "aff_c": aff_c, "maxp": maxp, "clm": clm,
        "mnd": mnd, "any_nb": any_nb,
    }


def flatten_roots(rt_list):
    """Flatten per-root tensors to example-major batch + root table.

    Example order within a root is (action, det, player); roots concatenate
    in list order. Returns (batch, table) where batch holds flat arrays and
    table holds per-root (start, count, na, actor, opp, teacher_means, tu,
    te) with tu/te shaped (na, D).
    """
    batch, table, pos = {}, [], 0
    for rt in rt_list:
        na = rt["na"]
        count = na * N_DETS * N_PLAYERS
        batch.setdefault("card", []).append(rt["card39"].reshape(-1, 15, 39))
        batch.setdefault("noble", []).append(rt["noble12"].reshape(-1, 5, 12))
        batch.setdefault("praw", []).append(rt["praw"].reshape(-1, 26))
        batch.setdefault("glob", []).append(rt["glob"].reshape(-1, 13))
        batch.setdefault("cmask", []).append(rt["cmask"].reshape(-1, 15))
        batch.setdefault("nmask", []).append(rt["nmask"].reshape(-1, 5))
        batch.setdefault("term", []).append(
            np.repeat(rt["term"][:, :, None], N_PLAYERS, axis=2).ravel())
        batch.setdefault("prog_t", []).append(
            (rt["prog"].reshape(-1).astype(np.float64) / PROGRESS_SCALE).astype(np.float32))
        batch.setdefault("mech_t", []).append(rt["mech"].reshape(-1, 4))
        batch.setdefault("has_nb", []).append(rt["has_nb"].ravel())
        batch.setdefault("aff_c", []).append(rt["aff_c"].ravel())
        batch.setdefault("maxp", []).append(rt["maxp"].ravel())
        batch.setdefault("clm", []).append(rt["clm"].ravel())
        batch.setdefault("mnd", []).append(rt["mnd"].ravel())
        batch.setdefault("any_nb", []).append(rt["any_nb"].ravel())
        q = rt["tu"][:, :, rt["actor"]].mean(axis=1)
        table.append({"start": pos, "count": count, "na": na,
                      "actor": rt["actor"], "opp": rt["opp"],
                      "teacher_means": [float(x) for x in q],
                      "tu": rt["tu"].astype(np.float64),
                      "te": rt["term"]})
        pos += count
    for k in ("card", "noble", "praw", "glob", "cmask", "nmask"):
        batch[k] = np.concatenate(batch[k], axis=0)
    for k in ("term", "prog_t", "has_nb", "aff_c", "maxp", "clm",
              "mnd", "any_nb"):
        batch[k] = np.concatenate(batch[k], axis=0)
    batch["mech_t"] = np.concatenate(batch["mech_t"], axis=0)
    return batch, table


@torch.no_grad()
def _forward_flat(model, batch, device):
    """Forward a flattened batch dict; returns numpy output arrays."""
    t = {k: torch.from_numpy(v).to(device) for k, v in batch.items()
         if k in ("card", "noble", "praw", "glob")}
    t["cmask"] = torch.from_numpy(batch["cmask"]).to(device)
    t["nmask"] = torch.from_numpy(batch["nmask"]).to(device)
    out = model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                       t["praw"], t["glob"])
    return {k: (v.detach().cpu().numpy() if isinstance(v, torch.Tensor) else v)
            for k, v in out.items()}


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
        # items: list of (gi, ri); returns flat batch tensors + root table.
        per_shard = {}
        for gi, ri in items:
            p = (train_store.paths[gi] if store is train_store else val_store.paths[gi])
            per_shard.setdefault(str(p), []).append(ri)
        rt_list = []
        for key, ris in per_shard.items():
            zpath = Path(key)
            z = (train_store.get(zpath, LOAD_KEYS) if store is train_store
                 else val_store.get(zpath, LOAD_KEYS))
            for ri in ris:
                rt_list.append(root_tensors(z, ri))
        return flatten_roots(rt_list)

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
            batch, table = load_batch(items, train_store)
            out = forward_batch(batch)
            prog_t = torch.from_numpy(batch["prog_t"]).to(device)
            term_m = torch.from_numpy(batch["term"]).to(device)
            learn_m = ~term_m
            if learn_m.any():
                l_prog = F.smooth_l1_loss(out["progress"][learn_m], prog_t[learn_m],
                                          beta=BETA_SMOOTHL1)
            else:
                l_prog = torch.zeros((), device=device)
            # mechanics
            ce_terms = []
            mech_t = torch.from_numpy(batch["mech_t"]).to(device)
            has_nb = torch.from_numpy(batch["has_nb"]).to(device)
            if learn_m.any():
                ce_terms.append(F.cross_entropy(out["aff_count"][learn_m], mech_t[learn_m, 0]))
                ce_terms.append(F.cross_entropy(out["aff_max"][learn_m], mech_t[learn_m, 1]))
            else:
                ce_terms += [torch.zeros((), device=device)] * 2
            nbm = learn_m & has_nb
            if nbm.any():
                ce_terms.append(F.cross_entropy(out["noble_claim"][nbm], mech_t[nbm, 2]))
                ce_terms.append(F.cross_entropy(out["noble_mindef"][nbm], mech_t[nbm, 3]))
            else:
                ce_terms += [torch.zeros((), device=device)] * 2
            l_mech = sum(ce_terms) / 4
            # rank: pairwise logistic over teacher strict pairs per root on
            # mean model scores; per-root pair mean, then batch mean over
            # roots that have at least one strict pair.
            prog_flat = out["progress"]
            l_rank_terms = []
            for rb in table:
                na, actor, opp = rb["na"], rb["actor"], rb["opp"]
                q = rb["teacher_means"]
                seg = prog_flat[rb["start"]:rb["start"] + rb["count"]].reshape(na, N_DETS, N_PLAYERS)
                tu_seg = torch.from_numpy(rb["tu"]).to(device)
                te_seg = torch.from_numpy(rb["te"]).to(device)
                # model mean per action: terminal bypass uses exact teacher
                pa = seg[:, :, actor]
                po = seg[:, :, opp]
                exact = tu_seg[:, :, actor]
                mns = torch.where(te_seg, exact, pa - po).float().mean(dim=1)
                # Vectorized ordered strict-pair mean (identical pair set to
                # the nested loop; required for large token-return roots).
                qv = torch.tensor(q, dtype=torch.float32, device=device)
                dq = qv[:, None] - qv[None, :]
                dm = mns[:, None] - mns[None, :]
                strict = dq != 0
                if strict.any():
                    l_rank_terms.append(
                        F.softplus(-torch.sign(dq[strict]) * dm[strict]).mean())
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
    per_shard = {}
    for gi, ri in index:
        per_shard.setdefault(gi, []).append(ri)
    aff_c_ok = aff_c_n = aff_m_ok = aff_m_n = 0
    clm_ok = clm_n = mnd_ok = mnd_n = 0
    save_pred = [] if save_prefix else None
    roots_total = 0
    opt_ok = 0
    sp_ok = sp_n = 0
    regrets = []
    zero_regret = 0
    saved_roots = []
    with torch.no_grad():
        for gi, ris in per_shard.items():
            zpath = store.paths[gi]
            z = store.get(zpath)
            batch, table = flatten_roots([root_tensors(z, ri) for ri in ris])
            t = {k: torch.from_numpy(v).to(device) for k, v in batch.items()
                 if k in ("card", "noble", "praw", "glob")}
            t["cmask"] = torch.from_numpy(batch["cmask"]).to(device)
            t["nmask"] = torch.from_numpy(batch["nmask"]).to(device)
            out = model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                               t["praw"], t["glob"])
            pa = np.stack([
                out["aff_count"].argmax(-1).cpu().numpy(),
                out["aff_max"].argmax(-1).cpu().numpy(),
                out["noble_claim"].argmax(-1).cpu().numpy(),
                out["noble_mindef"].argmax(-1).cpu().numpy()], axis=1)
            lt = np.stack([batch["aff_c"], batch["maxp"],
                           batch["clm"], batch["mnd"]], axis=1)
            nt = ~batch["term"]
            nb = batch["has_nb"] & nt
            aff_c_ok += int(((pa[:, 0] == lt[:, 0]) & nt).sum())
            aff_c_n += int(nt.sum())
            aff_m_ok += int(((pa[:, 1] == lt[:, 1]) & nt).sum())
            aff_m_n += int(nt.sum())
            clm_ok += int(((pa[:, 2] == lt[:, 2]) & nb).sum())
            clm_n += int(nb.sum())
            mnd_ok += int(((pa[:, 3] == lt[:, 3]) & nb).sum())
            mnd_n += int(nb.sum())
            if save_pred is not None:
                save_pred.append(np.concatenate(
                    [pa, lt, batch["has_nb"][:, None]], axis=1))
            prog = out["progress"].cpu().numpy().reshape(-1)
            for rb in table:
                na, actor, opp = rb["na"], rb["actor"], rb["opp"]
                seg = prog[rb["start"]:rb["start"] + rb["count"]].reshape(na, N_DETS, N_PLAYERS)
                tu = rb["tu"]
                te = rb["te"]
                q = np.array(rb["teacher_means"], dtype=np.float64)
                m = np.where(te, tu[:, :, actor],
                             seg[:, :, actor] - seg[:, :, opp]).mean(axis=1)
                roots_total += 1
                best = q.max()
                astar = set(np.flatnonzero(q == best).tolist())
                mhat = int(np.argmax(m))
                if mhat in astar:
                    opt_ok += 1
                dq = q[:, None] - q[None, :]
                dm = m[:, None] - m[None, :]
                strict = dq != 0
                sp_n += int(strict.sum())
                agree = (np.sign(dm[strict]) == np.sign(dq[strict])) & (dm[strict] != 0)
                sp_ok += int(agree.sum())
                rstar = float(q[np.argmax(q)])
                rhat = float(q[mhat])
                denom = max(rstar - float(q.min()), 1.0)
                r = (rstar - rhat) / denom
                regrets.append(r)
                if r == 0.0:
                    zero_regret += 1
                if save_prefix:
                    saved_roots.append({"teacher_means": q.tolist(),
                                        "model_means": m.tolist()})
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
                            preds=np.concatenate(save_pred, axis=0).astype(np.int64))
    return out


def evaluate_shift1(model, store, index, device):
    """Unseen SHIFT1 paired sensitivity on frozen test successors."""
    model.eval()
    per_shard = {}
    for gi, ri in index:
        per_shard.setdefault(gi, []).append(ri)
    stats = {k: {"changed": 0, "both_ok": 0, "sign_ok": 0} for k in
             ("aff_count", "aff_max", "claim", "mindef")}
    save_rows = []
    with torch.no_grad():
        for gi, ris in per_shard.items():
            zpath = store.paths[gi]
            z = store.get(zpath)
            bt, _ = flatten_roots([root_tensors(z, ri, shifted=False) for ri in ris])
            bs, _ = flatten_roots([root_tensors(z, ri, shifted=True) for ri in ris])
            ot = _forward_flat(model, bt, device)
            os_ = _forward_flat(model, bs, device)
            pt = np.stack([ot["aff_count"].argmax(-1), ot["aff_max"].argmax(-1),
                           ot["noble_claim"].argmax(-1), ot["noble_mindef"].argmax(-1)], axis=1)
            ps = np.stack([os_["aff_count"].argmax(-1), os_["aff_max"].argmax(-1),
                           os_["noble_claim"].argmax(-1), os_["noble_mindef"].argmax(-1)], axis=1)
            lt = np.stack([bt["aff_c"], bt["maxp"], bt["clm"], bt["mnd"]], axis=1)
            ls = np.stack([bs["aff_c"], bs["maxp"], bs["clm"], bs["mnd"]], axis=1)
            nt = ~bt["term"]
            nb = bt["has_nb"] & nt
            save_rows.append(np.concatenate(
                [pt, ps, lt, ls, bt["has_nb"][:, None]], axis=1))
            heads = [("aff_count", 0, False), ("aff_max", 1, False),
                     ("claim", 2, True), ("mindef", 3, True)]
            for name, j, noble_only in heads:
                keep = (nb if noble_only else nt)
                ltv, lsv = lt[keep, j], ls[keep, j]
                chg = ltv != lsv
                st = stats[name]
                st["changed"] += int(chg.sum())
                pti, psi = pt[keep, j][chg], ps[keep, j][chg]
                st["both_ok"] += int(((pti == ltv[chg]) & (psi == lsv[chg])).sum())
                st["sign_ok"] += int((np.sign(psi - pti) == np.sign(lsv[chg] - ltv[chg])).sum())
    np.savez_compressed(RUN_DIR / "shift1_preds.npz",
                        rows=np.concatenate(save_rows, axis=0).astype(np.int64))
    res = {}
    for k, st in stats.items():
        n = st["changed"]
        res[k] = {"changed_pairs": n,
                  "both_side_exact": st["both_ok"] / n if n else 0.0,
                  "signed_delta_acc": st["sign_ok"] / n if n else 0.0}
    return res


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
