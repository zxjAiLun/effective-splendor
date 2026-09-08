"""M48A frozen training + evaluation (exact DESIGN_V2 contract).

Recipe (frozen):
  training seed = 48_000_001; AdamW lr 1e-4, wd 1e-4, betas (0.9,0.999),
  eps 1e-8; 24 epochs; batch = 32 roots; grad clip 1.0; dropout 0;
  cosine to 1e-5.
  Loss = L_correction + L_retention + 0.01 * L_anchor (group means summed,
  never pooled); <=64 correction + <=64 retention pairs per root per epoch
  via deterministic hash; anchor = mean r^2.

G0 (before training, on ALL validation roots, 100% required):
  every nonterminal residual scalar == exactly 0.0
  every action residual == exactly 0.0
  q_corr float64 == q1 float64 exactly
  canonical selected action == n1 action

Checkpoint selection (validation only):
  retention_val >= 99.0% required to be a candidate;
  then highest capture, highest agreement, lowest regret, earliest epoch;
  no candidate => VALIDATION_ROUTE_FAIL => auto-FAIL.

Final gates (internal test AND M47S holdout, 8 checks):
  G1 capture >= 20%; G2 retention >= 99%; G3 agreement gain >= +3.0pp;
  G4 regret reduction >= 15%.

Performance note (2026-09-08 repair, no contract change):
  - No gc.collect() in hot loops; automatic GC only (verified stable).
  - Train pairs stored as compact numpy int16/int8 arrays instead of
    ~27.5M Python tuples; the (i, j, y) content, ordering, and the
    deterministic 64+64 subset selection are IDENTICAL to the tuple
    representation (same SHA-256 seed, same rng, same sorted indices).
  - Validation/eval residual computation batched per game (8 roots).
  - Per-epoch phase timing (data/gc-free) + process RSS peak tracked.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m46a_train import root_tensors, flatten_roots  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS = REPO / "local-artifacts/m46a-corpus"
LABELS = REPO / "local-artifacts/m48a-run/labels"
M47S_RAW = REPO / "local-artifacts/m47s-run/raw-records.json"
RUN_DIR = REPO / "local-artifacts/m48a-run"

TRAIN_SEED = 48_000_001
LR, WD, BETAS, EPS = 1e-4, 1e-4, (0.9, 0.999), 1e-8
EPOCHS, BATCH_ROOTS, CLIP, ETA_MIN = 24, 32, 1.0, 1e-5
N_DETS, N_PLAYERS = 4, 2
PAIR_CAP = 64
ANCHOR_W = 0.01
RETENTION_FLOOR = 0.99

SPLITS = {
    "train": (6_600_000, 6_601_791, "train"),
    "internal_test": (6_601_792, 6_602_047, "train"),
    "validation": (6_602_048, 6_602_303, "val"),
}
M47S_RANGE = (6_602_304, 6_602_559)


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024.0
        except Exception:
            pass
        return -1.0


def peak_rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().peak_wset / 1e6
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmHWM:"):
                        return float(line.split()[1]) / 1024.0
        except Exception:
            pass
        return -1.0


def set_deterministic():
    torch.manual_seed(TRAIN_SEED)
    np.random.seed(TRAIN_SEED % (2 ** 32))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def load_label_games(split: str) -> list[dict]:
    a, b, _ = SPLITS[split]
    games = []
    for seed in range(a, b + 1):
        p = LABELS / split / f"seed-{seed}.json"
        if not p.exists():
            raise RuntimeError(f"missing labels {p}")
        games.append(json.loads(p.read_text(encoding="utf-8")))
    return games


def load_features(seed: int):
    if 6_600_000 <= seed <= 6_602_047:
        d = CORPUS / "games" / "train"
    elif 6_602_048 <= seed <= 6_602_303:
        d = CORPUS / "games" / "val"
    elif 6_602_304 <= seed <= 6_602_559:
        d = CORPUS / "games" / "test"
    else:
        raise RuntimeError(f"seed {seed} out of corpus")
    return dict(np.load(d / f"seed-{seed}" / "shard.npz", allow_pickle=False))


def budget_record(root: dict, budget: int) -> dict:
    for rec in root["budgets"]:
        if rec["max_nodes"] == budget:
            return rec
    raise RuntimeError(f"budget {budget} missing")


def static_metrics(roots: list[dict]) -> dict:
    err = ok = 0
    regrets = []
    agree = 0
    for root in roots:
        b1, b2 = budget_record(root, 1), budget_record(root, 2000)
        sel1 = b1["selected"]
        i1 = b1["actions"].index(sel1)
        q2 = b2["utilities"]
        in_opt = i1 in b2["optimal_set"]
        if in_opt:
            ok += 1
        else:
            err += 1
        agree += in_opt
        r = (max(q2) - q2[i1]) / max(max(q2) - min(q2), 1)
        regrets.append(r)
    n = len(roots)
    return {"roots": n, "static_error_roots": err, "static_correct_roots": ok,
            "static_agreement": agree / n,
            "static_mean_regret": float(np.mean(regrets))}


def corrected_metrics(roots: list[dict], residuals: dict) -> dict:
    err_fixed = err_total = ok_kept = ok_total = 0
    regrets = []
    agree = 0
    for root in roots:
        b1, b2 = budget_record(root, 1), budget_record(root, 2000)
        sel1 = b1["selected"]
        i1 = b1["actions"].index(sel1)
        q1 = np.array(b1["utilities"], dtype=np.float64)
        q2 = np.array(b2["utilities"], dtype=np.float64)
        key = (root["observation_hash"], root["visible_history_hash"],
               root["information_set_hash"])
        r = residuals[key]
        D = max(q1.max() - q1.min(), 1.0)
        z1 = (q1 - q1.mean()) / D
        z_corr = z1 + np.array(r, dtype=np.float64)
        i_corr = int(np.argmax(z_corr))
        in_opt = i1 in b2["optimal_set"]
        corr_in_opt = i_corr in b2["optimal_set"]
        if in_opt:
            ok_total += 1
            ok_kept += corr_in_opt
        else:
            err_total += 1
            err_fixed += corr_in_opt
        agree += corr_in_opt
        regrets.append((q2.max() - q2[i_corr]) / max(q2.max() - q2.min(), 1))
    n = len(roots)
    return {
        "roots": n,
        "capture": (err_fixed / err_total) if err_total else 0.0,
        "capture_count": err_fixed, "error_total": err_total,
        "retention": (ok_kept / ok_total) if ok_total else 1.0,
        "retention_count": ok_kept, "correct_total": ok_total,
        "agreement": agree / n,
        "mean_regret": float(np.mean(regrets)),
    }


@torch.no_grad()
def compute_residuals(model, label_games, device, shard_cache=None):
    """Batched (per game = 8 roots) residual inference; identity->residuals."""
    model.eval()
    out = {}
    by_game = {}
    for g in label_games:
        by_game[g["game_seed"]] = g
    for seed, g in by_game.items():
        if shard_cache is not None and seed in shard_cache:
            z = shard_cache[seed]
        else:
            z = load_features(seed)
            if shard_cache is not None:
                if len(shard_cache) > 8:
                    shard_cache.clear()
                shard_cache[seed] = z
        step_to_ri = {int(z["root_meta"][c][0]): c
                      for c in range(z["n_actions"].shape[0])}
        rt_list = []
        root_list = []
        for root in g["roots"]:
            ri = step_to_ri[root["step_index"]]
            rt_list.append(root_tensors(z, ri))
            root_list.append(root)
        batch, table = flatten_roots(rt_list)
        t = {k: torch.from_numpy(v).to(device)
             for k, v in batch.items() if k in ("card", "noble", "praw", "glob")}
        t["cmask"] = torch.from_numpy(batch["cmask"]).to(device)
        t["nmask"] = torch.from_numpy(batch["nmask"]).to(device)
        h = model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                         t["praw"], t["glob"])
        u = model.residual(h).squeeze(-1)
        for k, root in enumerate(root_list):
            rb = table[k]
            na = rb["na"]
            actor = rb["actor"]
            opp = 1 - actor
            uk = u[rb["start"]:rb["start"] + rb["count"]].reshape(na, N_DETS, N_PLAYERS)
            te = torch.from_numpy(rb["te"]).to(device)
            uk = torch.where(te.unsqueeze(-1), torch.zeros_like(uk), uk)
            # Actor-viewpoint residual (contract): h(s,actor) - h(s,1-actor).
            r = (uk[:, :, actor] - uk[:, :, opp]).mean(dim=1)
            key = (root["observation_hash"], root["visible_history_hash"],
                   root["information_set_hash"])
            out[key] = r.cpu().numpy().tolist()
    return out


def root_pairs_compact(root: dict):
    """Teacher-strict pairs as compact numpy arrays (identical content and
    order to the original tuple lists): corr/ret are (P,3) int16 arrays with
    columns [i, j, y] (y in {1,-1})."""
    b1, b2 = budget_record(root, 1), budget_record(root, 2000)
    q1 = np.array(b1["utilities"], dtype=np.float64)
    q2 = np.array(b2["utilities"], dtype=np.float64)
    corr_i, corr_j, corr_y = [], [], []
    ret_i, ret_j, ret_y = [], [], []
    n = len(q2)
    for i in range(n):
        for j in range(i + 1, n):
            if q2[i] == q2[j]:
                continue
            y = 1 if q2[i] > q2[j] else -1
            d1 = q1[i] - q1[j]
            if y * d1 <= 0:
                corr_i.append(i); corr_j.append(j); corr_y.append(y)
            else:
                ret_i.append(i); ret_j.append(j); ret_y.append(y)
    corr = np.stack([np.array(corr_i, dtype=np.int16),
                     np.array(corr_j, dtype=np.int16),
                     np.array(corr_y, dtype=np.int8)], axis=1) if corr_i \
        else np.zeros((0, 3), dtype=np.int16)
    ret = np.stack([np.array(ret_i, dtype=np.int16),
                    np.array(ret_j, dtype=np.int16),
                    np.array(ret_y, dtype=np.int8)], axis=1) if ret_i \
        else np.zeros((0, 3), dtype=np.int16)
    return q1, q2, corr, ret


def det_pair_subset_idx(n_pairs: int, cap: int, seed_mat: int, epoch: int,
                        root_key: str):
    """Deterministic subset INDICES (same SHA-256 seed and rng as the tuple
    version; identical selection given identical pair order)."""
    if n_pairs <= cap:
        return None  # means: use all
    payload = f"{seed_mat}|{epoch}|{root_key}".encode("utf-8")
    h = int.from_bytes(hashlib.sha256(payload).digest()[:8], "little")
    rng = np.random.default_rng(h)
    return np.sort(rng.choice(n_pairs, size=cap, replace=False))


def vectorized_root_loss(r, z1t, pairs):
    """pairs: (P,3) int array [i, j, y]; r/z1t: (na,) tensors."""
    if pairs.shape[0] == 0:
        return None
    ii = torch.from_numpy(pairs[:, 0].astype(np.int64)).to(r.device)
    jj = torch.from_numpy(pairs[:, 1].astype(np.int64)).to(r.device)
    yy = torch.from_numpy(pairs[:, 2].astype(np.float32)).to(r.device)
    m = yy * ((z1t[ii] - z1t[jj]) + (r[ii] - r[jj]))
    return F.softplus(-m).mean()


def g0_zero_init(model, val_games, device, shard_cache) -> dict:
    """G0 (full contract): exact zero residuals AND bit-exact scoring
    equivalence — q_corr float64 == q1 float64 exactly, canonical selected
    action == n1 action — on ALL validation roots."""
    if not model.assert_zero_init():
        return {"pass": False, "reason": "residual head not zero"}
    residuals = compute_residuals(model, val_games, device, shard_cache)
    n_roots = n_actions = 0
    q_exact = action_exact = 0
    for root in [r for g in val_games for r in g["roots"]]:
        b1 = budget_record(root, 1)
        key = (root["observation_hash"], root["visible_history_hash"],
               root["information_set_hash"])
        r = residuals[key]
        if len(r) != len(b1["utilities"]):
            return {"pass": False, "reason": "residual length mismatch"}
        for x in r:
            if x != 0.0:
                return {"pass": False, "reason": f"nonzero residual {x}"}
        q1 = np.array(b1["utilities"], dtype=np.float64)
        D = max(q1.max() - q1.min(), 1.0)
        q_corr = q1 + D * np.array(r, dtype=np.float64)
        if not np.array_equal(q_corr.view(np.int64), q1.view(np.int64)):
            return {"pass": False, "reason": "q_corr != q1 bitwise"}
        q_exact += 1
        z1 = (q1 - q1.mean()) / D
        z_corr = z1 + np.array(r, dtype=np.float64)
        i_corr = int(np.argmax(z_corr))
        sel_n1 = b1["selected"]
        corr_action = b1["actions"][i_corr]
        if corr_action != sel_n1:
            return {"pass": False, "reason": "selected action differs from n1"}
        action_exact += 1
        n_roots += 1
        n_actions += len(r)
    return {"pass": True, "roots": n_roots, "actions": n_actions,
            "q_bitexact_roots": q_exact, "action_exact_roots": action_exact}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    set_deterministic()
    device = torch.device(args.device)
    from splendor_gpu.m48a_model import ResidualSuccessorNet
    model = ResidualSuccessorNet().to(device)

    print("Loading labels...", flush=True)
    train_games = load_label_games("train")
    val_games = load_label_games("validation")
    itest_games = load_label_games("internal_test")
    m47s_games = json.loads(M47S_RAW.read_text(encoding="utf-8"))

    # Shared bounded shard cache (no gc.collect; automatic GC only).
    shard_cache: dict[int, dict] = {}

    # G0 before training
    print("G0 zero-init gate (all validation roots)...", flush=True)
    g0 = g0_zero_init(model, val_games, device, shard_cache)
    print("G0:", json.dumps(g0), flush=True)
    if not g0["pass"]:
        raise SystemExit("FAIL_BEFORE_TRAINING: " + g0.get("reason", "?"))
    (RUN_DIR / "g0.json").write_text(json.dumps(g0), encoding="utf-8")

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD,
                            betas=BETAS, eps=EPS)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS,
                                                       eta_min=ETA_MIN)

    # Pre-assemble train root data (compact arrays) once.
    t_asm = time.time()
    print("Assembling training roots (compact pair arrays)...", flush=True)
    train_roots = []  # (game_seed, root_obj, q1, q2, corr(P,3), ret(P,3), ri)
    n_corr_pairs = n_ret_pairs = 0
    for g in train_games:
        z = load_features(g["game_seed"])
        step_to_ri = {int(z["root_meta"][c][0]): c
                      for c in range(z["n_actions"].shape[0])}
        for root in g["roots"]:
            ri = step_to_ri[root["step_index"]]
            q1, q2, corr, ret = root_pairs_compact(root)
            n_corr_pairs += corr.shape[0]
            n_ret_pairs += ret.shape[0]
            train_roots.append((g["game_seed"], root, q1, q2, corr, ret, ri))
    print(f"  {len(train_roots)} roots assembled; "
          f"corr pairs={n_corr_pairs:,}, ret pairs={n_ret_pairs:,} "
          f"({time.time()-t_asm:.0f}s; RSS {rss_mb():.0f}MB)", flush=True)

    history = []
    best = None
    best_epoch = -1
    best_ret_key = None
    n_games = len(train_games)
    game_seeds = [g_["game_seed"] for g_ in train_games]

    def get_shard(seed):
        if seed not in shard_cache:
            if len(shard_cache) > 8:
                shard_cache.clear()  # no gc.collect(); automatic GC only
            shard_cache[seed] = load_features(seed)
        return shard_cache[seed]

    # Index train roots by game seed for exact batch assembly.
    roots_by_seed: dict[int, list] = {}
    for tr in train_roots:
        roots_by_seed.setdefault(tr[0], []).append(tr)

    phase_times = {"data_s": 0.0, "train_s": 0.0, "val_s": 0.0}

    for epoch in range(EPOCHS):
        model.train()
        gen = torch.Generator().manual_seed(TRAIN_SEED + epoch)
        gperm = torch.randperm(n_games, generator=gen).tolist()
        batches = [gperm[i:i + 4] for i in range(0, n_games, 4)]
        tot_loss = tot_corr_l = tot_ret_l = nb = 0
        t0 = time.time()
        t_data = t_train = 0.0
        for b_games in batches:
            roots_here = []
            for gi in b_games:
                roots_here.extend(roots_by_seed[game_seeds[gi]])
            if not roots_here:
                continue
            # ---- data phase ----
            ta = time.time()
            rt_list = []
            meta = []
            for (seed_, root, q1, q2, corr, ret, ri) in roots_here:
                z = get_shard(seed_)
                rt = root_tensors(z, ri)
                rt_list.append(rt)
                meta.append((root, q1, q2, corr, ret))
            batch, table = flatten_roots(rt_list)
            t = {k: torch.from_numpy(v).to(device)
                 for k, v in batch.items() if k in ("card", "noble", "praw", "glob")}
            t["cmask"] = torch.from_numpy(batch["cmask"]).to(device)
            t["nmask"] = torch.from_numpy(batch["nmask"]).to(device)
            t_data += time.time() - ta
            # ---- train phase ----
            tb = time.time()
            h = model.encode(t["card"], t["cmask"], t["noble"], t["nmask"],
                             t["praw"], t["glob"])
            u = model.residual(h).squeeze(-1)
            corr_losses, ret_losses, anchors = [], [], []
            for k, (root, q1, q2, corr, ret) in enumerate(meta):
                rb = table[k]
                na = rb["na"]
                actor = rb["actor"]
                opp = 1 - actor
                uk = u[rb["start"]:rb["start"] + rb["count"]].reshape(na, N_DETS, N_PLAYERS)
                te = torch.from_numpy(rb["te"]).to(device)
                uk = torch.where(te.unsqueeze(-1), torch.zeros_like(uk), uk)
                # Actor-viewpoint residual (contract): h(s,actor)-h(s,1-actor).
                r = (uk[:, :, actor] - uk[:, :, opp]).mean(dim=1)
                anchors.append((r ** 2).mean())
                D = max(q1.max() - q1.min(), 1.0)
                z1 = (q1 - q1.mean()) / D
                z1t = torch.tensor(z1, dtype=torch.float32, device=device)
                key = root["information_set_hash"]
                ci = det_pair_subset_idx(corr.shape[0], PAIR_CAP,
                                         TRAIN_SEED, epoch, key)
                cs = corr if ci is None else corr[ci]
                ri_ = det_pair_subset_idx(ret.shape[0], PAIR_CAP,
                                          TRAIN_SEED, epoch, key)
                rs = ret if ri_ is None else ret[ri_]
                lc = vectorized_root_loss(r, z1t, cs)
                if lc is not None:
                    corr_losses.append(lc)
                lr_ = vectorized_root_loss(r, z1t, rs)
                if lr_ is not None:
                    ret_losses.append(lr_)
            l_corr = (sum(corr_losses) / len(corr_losses)) if corr_losses \
                else torch.zeros((), device=device)
            l_ret = (sum(ret_losses) / len(ret_losses)) if ret_losses \
                else torch.zeros((), device=device)
            l_anchor = (sum(anchors) / len(anchors)) if anchors \
                else torch.zeros((), device=device)
            loss = l_corr + l_ret + ANCHOR_W * l_anchor
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            opt.step()
            tot_loss += loss.item()
            tot_corr_l += l_corr.item()
            tot_ret_l += l_ret.item()
            nb += 1
            t_train += time.time() - tb
        sched.step()
        t_train_total = time.time() - t0

        # ---- validation phase (batched per game) ----
        tv = time.time()
        residuals = compute_residuals(model, val_games, device, shard_cache)
        val_roots = [r for g in val_games for r in g["roots"]]
        vm = corrected_metrics(val_roots, residuals)
        sm = static_metrics(val_roots)
        val_s = time.time() - tv

        retention = vm["retention"]
        candidate = retention >= RETENTION_FLOOR
        key = (round(vm["capture"], 12), round(vm["agreement"], 12),
               round(-vm["mean_regret"], 12), -epoch)
        improved = candidate and (best is None or key > best)
        if improved:
            best = key
            best_epoch = epoch
            torch.save(model.state_dict(), RUN_DIR / "best.pt")
        ret_key = (round(retention, 12), -epoch)
        if best_ret_key is None or ret_key > best_ret_key:
            best_ret_key = ret_key
            torch.save(model.state_dict(), RUN_DIR / "route-fail-checkpoint.pt")
        history.append({
            "epoch": epoch, "train_loss": tot_loss / max(nb, 1),
            "train_corr": tot_corr_l / max(nb, 1),
            "train_ret": tot_ret_l / max(nb, 1),
            "val_retention": retention, "val_capture": vm["capture"],
            "val_agreement": vm["agreement"], "val_regret": vm["mean_regret"],
            "static_agreement": sm["static_agreement"],
            "candidate": candidate, "best_epoch": best_epoch,
            "phase_data_s": round(t_data, 1),
            "phase_train_s": round(t_train, 1),
            "phase_val_s": round(val_s, 1),
            "epoch_wall_s": round(t_train_total, 1),
            "rss_mb": round(rss_mb(), 0),
        })
        phase_times["data_s"] += t_data
        phase_times["train_s"] += t_train
        phase_times["val_s"] += val_s
        print(f"epoch {epoch:02d} loss={tot_loss/max(nb,1):.4f} "
              f"corr={tot_corr_l/max(nb,1):.4f} ret={tot_ret_l/max(nb,1):.4f} "
              f"val_ret={retention:.4f} val_cap={vm['capture']:.4f} "
              f"val_agr={vm['agreement']:.4f} best={best_epoch} "
              f"[data {t_data:.0f}s train {t_train:.0f}s val {val_s:.0f}s] "
              f"rss={rss_mb():.0f}MB", flush=True)

    (RUN_DIR / "epoch_metrics.json").write_text(json.dumps(history, indent=2))
    route_ok = any(h["candidate"] for h in history)
    print(f"BEST EPOCH: {best_epoch}; VALIDATION_ROUTE_OK: {route_ok}")
    print(f"Phase totals: {json.dumps(phase_times)}; "
          f"peak RSS {peak_rss_mb():.0f}MB", flush=True)

    if route_ok:
        model.load_state_dict(torch.load(RUN_DIR / "best.pt", map_location=device))
    else:
        model.load_state_dict(
            torch.load(RUN_DIR / "route-fail-checkpoint.pt", map_location=device))
        print("VALIDATION_ROUTE_FAIL: evaluating highest-retention fallback "
              "checkpoint for the record only.", flush=True)
    results = {"best_epoch": best_epoch,
               "validation_route_ok": route_ok, "history": history,
               "phase_totals": phase_times,
               "peak_rss_mb": peak_rss_mb()}

    for name, games in (("internal_test", itest_games), ("m47s_holdout", m47s_games)):
        roots = [r for g in games for r in g["roots"]]
        sm = static_metrics(roots)
        residuals = compute_residuals(model, games, device, shard_cache)
        cm = corrected_metrics(roots, residuals)
        gates = {
            "G1_capture": {"value": cm["capture"], "threshold": 0.20,
                           "pass": cm["capture"] >= 0.20},
            "G2_retention": {"value": cm["retention"], "threshold": 0.99,
                             "pass": cm["retention"] >= 0.99},
            "G3_agreement_gain": {
                "value": cm["agreement"] - sm["static_agreement"],
                "threshold": 0.03,
                "pass": (cm["agreement"] - sm["static_agreement"]) >= 0.03},
            "G4_regret_reduction": {
                "value": (sm["static_mean_regret"] - cm["mean_regret"])
                         / sm["static_mean_regret"]
                if sm["static_mean_regret"] > 0 else 0.0,
                "threshold": 0.15,
                "pass": sm["static_mean_regret"] > 0
                and ((sm["static_mean_regret"] - cm["mean_regret"])
                     / sm["static_mean_regret"]) >= 0.15},
        }
        results[name] = {"static": sm, "corrected": cm, "gates": gates}
        print(f"\n[{name}]")
        print("  static:", {k: round(v, 4) for k, v in sm.items()
                            if isinstance(v, float)})
        print("  corrected:", {k: round(v, 4) for k, v in cm.items()
                               if isinstance(v, float)})
        for gn, gv in gates.items():
            print(f"  {gn}: {gv['value']:.4f} (>= {gv['threshold']})"
                  f" -> {'PASS' if gv['pass'] else 'FAIL'}")

    overall = (route_ok
               and all(gv["pass"] for gn, gv in results["internal_test"]["gates"].items())
               and all(gv["pass"] for gn, gv in results["m47s_holdout"]["gates"].items()))
    verdict = "STATIC_PRIOR_RESIDUAL_LEARNABLE" if overall \
        else "STATIC_PRIOR_RESIDUAL_NOT_VALIDATED"
    results["verdict"] = verdict
    print(f"\nVERDICT: {verdict}")
    (RUN_DIR / "final_metrics.json").write_text(
        json.dumps(results, indent=2, default=lambda o: float(o)
                   if isinstance(o, (np.floating,)) else int(o)
                   if isinstance(o, (np.integer,)) else str(o)))


if __name__ == "__main__":
    main()
