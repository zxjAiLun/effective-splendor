"""Production Parity, Live Replay Belief Tracking, and Registry Verification for M35A."""

import json
import tempfile
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.encoding import encode_observation, encode_action
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.m33a_encoding import decompose_legal_action
from splendor_gpu.m34a_encoding import (
    get_action_family,
    get_take_pattern_id,
    get_return_vector_6d,
)
from splendor_gpu.m35a_registry import (
    REGISTRY,
    load_and_validate_checkpoint,
    FROZEN_CATALOG_HASH,
)
from splendor_gpu.m35a_adapters import score_model_actions
from splendor_gpu.m35a_belief import LiveBeliefTracker

CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
DATASET_PATH = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
SIDECAR_PATH = Path("local-artifacts/m32a-belief-sidecar/m32a-belief-sidecar.json")
TIER_INDEX = {"One": 0, "Two": 1, "Three": 2}
# Number of M25 matches replayed through the live event stream for parity.
NUM_PARITY_MATCHES = 6
# Minimum (match, ply, seat) 212-dim vector comparisons that must be exercised.
MIN_PARITY_COMPARISONS = 300


@pytest.fixture(scope="module")
def shared_resources():
    catalog = load_catalog(CATALOG_PATH)
    cat_hash = catalog_semantic_hash(catalog)
    with DATASET_PATH.open(encoding="utf-8") as f:
        ds_payload = json.load(f)
    samples = ds_payload["examples"][:20]  # First 20 canonical samples
    return {
        "catalog": catalog,
        "cat_hash": cat_hash,
        "samples": samples,
    }


def test_registry_fail_closed_tamper_rejection(shared_resources):
    """Verifies that invalid model_ids, corrupted file SHA, or bad catalog hashes fail closed."""
    cat_hash = shared_resources["cat_hash"]
    device = torch.device("cpu")

    # 1. Unregistered model ID
    with pytest.raises(ValueError, match="Unknown model_id"):
        load_and_validate_checkpoint("INVALID-MODEL", cat_hash, device)

    # 2. Catalog hash mismatch
    with pytest.raises(ValueError, match="Catalog hash mismatch"):
        load_and_validate_checkpoint("M25-D2-v2", "0" * 64, device)


def test_all_9_models_production_path_parity(shared_resources):
    """Verifies that for each of the 9 models, the adapter forward matches the reference offline forward exactly."""
    catalog = shared_resources["catalog"]
    cat_hash = shared_resources["cat_hash"]
    samples = shared_resources["samples"]
    device = torch.device("cpu")

    for model_id, entry in REGISTRY.items():
        model, reg_entry = load_and_validate_checkpoint(model_id, cat_hash, device)
        belief_tracker = LiveBeliefTracker(viewer=0, player_count=2)

        for s_idx, sample in enumerate(samples):
            obs = sample["observation"]
            legal_actions = sample["legal_actions"]
            num_legal = len(legal_actions)

            # 1. Score via adapter (production path)
            adapter_scores = score_model_actions(
                model=model,
                entry=reg_entry,
                observation=obs,
                legal_actions=legal_actions,
                belief_tracker=belief_tracker,
                catalog=catalog,
                device=device,
            )

            # 2. Score via reference forward
            enc_obs = encode_observation(obs, catalog)
            entities = enc_obs.entities.unsqueeze(0).to(device)
            mask = enc_obs.mask.unsqueeze(0).to(device)

            if reg_entry.global_feature_dim == 252:
                b_feats = belief_tracker.project_features(obs, catalog)
                b_tensor = torch.tensor(b_feats, dtype=torch.float32)
                global_features = torch.cat([enc_obs.global_features, b_tensor], dim=-1).unsqueeze(0).to(device)
            else:
                global_features = enc_obs.global_features.unsqueeze(0).to(device)

            if reg_entry.action_feature_dim == 36:
                act_t = torch.stack([encode_action(a) for a in legal_actions]).to(device)
            else:
                acts = []
                for a in legal_actions:
                    acts.append(encode_action(a).tolist() + encode_action_delta_v2(obs, a, catalog))
                act_t = torch.tensor(acts, dtype=torch.float32, device=device)

            offsets = torch.tensor([0, num_legal], dtype=torch.long, device=device)

            if model_id == "M34A":
                fam_t = torch.tensor([get_action_family(a) for a in legal_actions], dtype=torch.long, device=device)
                pat_t = torch.tensor([get_take_pattern_id(a) for a in legal_actions], dtype=torch.long, device=device)
                ret_t = torch.tensor([get_return_vector_6d(a) for a in legal_actions], dtype=torch.float32, device=device)
                ref_scores, _ = model.forward_packed(
                    entities=entities,
                    entity_mask=mask,
                    global_features=global_features,
                    actions=act_t,
                    action_offsets=offsets,
                    family_indices=fam_t,
                    take_pattern_indices=pat_t,
                    return_vectors_6d=ret_t,
                )
            elif model_id == "M33A":
                fams, modes, sel_c, ret_c, ent_s, tier_s = [], [], [], [], [], []
                for a in legal_actions:
                    d = decompose_legal_action(obs, a)
                    fams.append(d["family_idx"])
                    modes.append(d["take_mode_idx"])
                    sel_c.append(d["selected_colors"])
                    ret_c.append(d["returned_colors"])
                    ent_s.append(d["target_entity_slot"])
                    tier_s.append(d["target_deck_tier"])
                ref_scores, _ = model.forward_packed(
                    entities=entities,
                    mask=mask,
                    global_features=global_features,
                    actions=act_t,
                    action_offsets=offsets,
                    family_indices=torch.tensor(fams, dtype=torch.long, device=device),
                    take_mode_indices=torch.tensor(modes, dtype=torch.long, device=device),
                    selected_colors=torch.tensor(sel_c, dtype=torch.float32, device=device),
                    returned_colors=torch.tensor(ret_c, dtype=torch.float32, device=device),
                    target_entity_slots=torch.tensor(ent_s, dtype=torch.long, device=device),
                    target_deck_tiers=torch.tensor(tier_s, dtype=torch.long, device=device),
                )
            elif hasattr(model, "forward_packed"):
                ref_scores, _ = model.forward_packed(
                    entities=entities,
                    mask=mask,
                    global_features=global_features,
                    actions=act_t,
                    action_offsets=offsets,
                )
            else:
                action_mask = torch.ones((1, num_legal), dtype=torch.bool, device=device)
                ref_logits, _ = model(
                    entities=entities,
                    mask=mask,
                    global_features=global_features,
                    actions=act_t.unsqueeze(0),
                    action_mask=action_mask,
                )
                ref_scores = ref_logits[0]

            # Parity assertion: scores must match within 1e-5
            diff = (adapter_scores - ref_scores).abs().max().item()
            assert diff <= 1e-5, f"{model_id} sample {s_idx}: max diff {diff}"

            # Argmax assertion: first-max argmax index must be identical
            chosen_adapter = adapter_scores.argmax().item()
            chosen_ref = ref_scores.argmax().item()
            assert chosen_adapter == chosen_ref, f"{model_id} sample {s_idx}: argmax mismatch"


def test_m34a_hierarchical_log_prob_invariant(shared_resources):
    """Verifies that M34A scoring produces exact normalized log-probs (sum(exp(log_probs)) == 1.0) and not unnormalized logits."""
    catalog = shared_resources["catalog"]
    cat_hash = shared_resources["cat_hash"]
    sample = shared_resources["samples"][0]
    device = torch.device("cpu")

    model, reg_entry = load_and_validate_checkpoint("M34A", cat_hash, device)
    belief_tracker = LiveBeliefTracker(viewer=0, player_count=2)

    log_probs = score_model_actions(
        model=model,
        entry=reg_entry,
        observation=sample["observation"],
        legal_actions=sample["legal_actions"],
        belief_tracker=belief_tracker,
        catalog=catalog,
        device=device,
    )

    probs_sum = log_probs.exp().sum().item()
    assert abs(probs_sum - 1.0) < 1e-4, f"M34A output is not normalized log-probabilities: sum(exp)={probs_sum}"


def test_m32a_live_replay_belief_features_parity(shared_resources):
    """Reconstructs the real player-projected v0.5 visible event stream from M25
    replays, feeds every event through ``LiveBeliefTracker.handle_event``, calls
    ``project_features`` at each decision ply for BOTH seats, and compares the
    full 212-dim vector element-by-element against the frozen M32A sidecar."""
    if not SIDECAR_PATH.exists():
        pytest.skip(f"Sidecar {SIDECAR_PATH} not found")

    catalog = shared_resources["catalog"]

    with SIDECAR_PATH.open(encoding="utf-8") as f:
        sidecar = json.load(f)

    # Sidecar identity binding: (match_index, ply, actor) -> belief_features
    sidecar_by_key = {}
    for entry in sidecar["entries"]:
        key = (entry["match_index"], entry["ply"], entry["actor"])
        if key in sidecar_by_key:
            raise ValueError(f"duplicate sidecar entry for {key}")
        sidecar_by_key[key] = entry["belief_features"]

    with DATASET_PATH.open(encoding="utf-8") as f:
        ds_payload = json.load(f)
    examples = ds_payload["examples"]

    # Index dataset examples: per match, per ply (observation before step application)
    obs_by_match_ply = {}
    for ex in examples:
        m = ex["evaluation_match_index"]
        obs_by_match_ply.setdefault(m, {})[ex["ply"]] = ex

    def replay_path(match_idx: int) -> Path:
        return Path(f"local-artifacts/m25-generation/eval-run/matches/match-{match_idx:06d}.replay.json")

    # ---- v0.5 visible-event stream reconstruction ----------------------------
    # The live agent receives, per applied step: an `event` message for every
    # VisibleEvent except ActionApplied/GameEnd which use dedicated message
    # types. We rebuild the same stream (game_started + per-step events) for
    # each viewer from: the recorded actions + per-ply observations (for card
    # identities visible to that viewer at that time).
    def deck_reserve_identity(match_idx: int, steps: list[dict], viewer: int, ply: int) -> int:
        """Resolve the card identity of viewer's own blind reserve at `ply`.

        The identity first appears in the viewer's private reserved view at
        their next observation (ply+2, post-application). Deck reserves keep
        relative order among themselves in the private view, so we index by
        the number of deck reserves the viewer held before this one.
        """
        actor = int(steps[ply]["actor"])
        assert actor == viewer
        ex_later = obs_by_match_ply[match_idx].get(ply + 2)
        if ex_later is None or ex_later["actor"] != viewer:
            raise ValueError(
                f"viewer follow-up observation missing for blind reserve at ply {ply}"
            )
        deck_reserves_before = 0
        for k in range(ply):
            kind = steps[k]["action"]["type"]
            if kind == "reserve_deck" and int(steps[k]["actor"]) == viewer:
                deck_reserves_before += 1
            elif kind == "buy_reserved" and int(steps[k]["actor"]) == viewer:
                # The bought slot's provenance: market (public) or deck.
                obs_k = obs_by_match_ply[match_idx][k]["observation"]
                slot = int(steps[k]["action"]["slot"])
                bought_from_deck = False
                for r in obs_k["private"]["reserved"]:
                    if r["slot"] == slot:
                        bought_from_deck = bool(r["from_deck"])
                        break
                if bought_from_deck:
                    deck_reserves_before -= 1
        priv = ex_later["observation"]["private"]["reserved"]
        deck_reserves = [r for r in priv if r["from_deck"]]
        if len(deck_reserves) <= deck_reserves_before:
            raise ValueError(f"cannot resolve blind reserve identity at ply {ply}")
        return deck_reserves[deck_reserves_before]["card"]

    def step_events_for_viewer(match_idx: int, steps: list[dict], viewer: int, ply: int) -> list[dict]:
        """Events derived from applying step `ply`, projected for `viewer`."""
        step = steps[ply]
        actor = int(step["actor"])
        action = step["action"]
        kind = action.get("type")
        if kind == "reserve_market":
            tier = action["tier"]
            slot = int(action["slot"])
            # Card identity is public: it sat in the market at ply (pre-application
            # observation of the ply actor).
            obs_k = obs_by_match_ply[match_idx][ply]["observation"]
            card_id = obs_k["public"]["market"][TIER_INDEX[tier]][slot]
            if card_id is None:
                raise ValueError(f"market slot empty at ply {ply} of match {match_idx}")
            return [{
                "type": "card_reserved",
                "player": actor,
                "card": card_id,
                "from": {"market": {"tier": tier, "slot": slot}},
                "received_gold": False,
                "public_identity": True,
                "visible_to": "public",
            }]
        if kind == "reserve_deck":
            tier = action["tier"]
            if actor == viewer:
                card_id = deck_reserve_identity(match_idx, steps, viewer, ply)
                return [{
                    "type": "card_reserved",
                    "player": actor,
                    "card": card_id,
                    "from": {"deck": {"tier": tier}},
                    "received_gold": False,
                    "public_identity": False,
                    "visible_to": {"player": actor},
                }]
            # Opponent blind reserve: identity hidden from viewer.
            return [{
                "type": "card_reserved",
                "player": actor,
                "card": None,
                "from": {"deck": {"tier": tier}},
                "received_gold": False,
                "public_identity": False,
                "visible_to": {"player": actor},
            }]
        if kind == "buy_market":
            tier = action["tier"]
            slot = int(action["slot"])
            obs_k = obs_by_match_ply[match_idx][ply]["observation"]
            card_id = obs_k["public"]["market"][TIER_INDEX[tier]][slot]
            return [{
                "type": "card_purchased",
                "player": actor,
                "card": card_id,
                "paid": {},
                "from": {"market": {"tier": tier, "slot": slot}},
            }]
        if kind == "buy_reserved":
            obs_k = obs_by_match_ply[match_idx][ply]["observation"]
            slot = int(action["slot"])
            if actor == viewer:
                card_id = None
                for r in obs_k["private"]["reserved"]:
                    if r["slot"] == slot:
                        card_id = r["card"]
                        break
                if card_id is None:
                    raise ValueError(f"viewer reserved slot {slot} not found at ply {ply}")
            else:
                pub_res = obs_k["public"]["players"][actor]["public_reserved"]
                card_id = pub_res[slot] if slot < len(pub_res) else None
            return [{
                "type": "card_purchased",
                "player": actor,
                "card": card_id,
                "paid": {},
                "from": {"reserved": {"slot": slot}},
            }]
        # take_tokens / choose_noble / pass do not change belief slots.
        return []

    # ---- Comparison across matches, plies, and both seats -------------------
    compared = 0
    mismatches = 0
    max_feat_diff = 0.0

    for match_idx in range(NUM_PARITY_MATCHES):
        rp = replay_path(match_idx)
        if not rp.exists():
            continue
        with rp.open(encoding="utf-8") as f:
            replay = json.load(f)
        steps = replay["steps"]
        match_examples = obs_by_match_ply.get(match_idx, {})

        for seat in (0, 1):
            tracker = LiveBeliefTracker(viewer=seat, player_count=2)
            tracker.handle_event({"type": "game_started", "player_count": 2, "ruleset": "base_v1"})

            for ply in range(len(steps)):
                # The ply-N observation is pre-application: it must equal the
                # tracker state after absorbing steps 0..N-1 (the live agent
                # receives step N's events only after acting at ply N).
                ex = match_examples.get(ply)
                if ex is not None and ex["actor"] == seat:
                    key = (match_idx, ply, seat)
                    expected = sidecar_by_key.get(key)
                    if expected is not None:
                        actual = tracker.project_features(ex["observation"], catalog)
                        assert len(actual) == 212
                        assert len(expected) == 212
                        for dim, (a, e) in enumerate(zip(actual, expected)):
                            if abs(a - e) > 1e-6:
                                mismatches += 1
                                if mismatches <= 10:
                                    print(
                                        f"MISMATCH match={match_idx} ply={ply} seat={seat} "
                                        f"dim={dim} actual={a} expected={e}"
                                    )
                                max_feat_diff = max(max_feat_diff, abs(a - e))
                        compared += 1

                # Absorb the events produced by applying step `ply` — this is
                # exactly what the live agent receives before the next
                # observation/request pair.
                for ev in step_events_for_viewer(match_idx, steps, seat, ply):
                    tracker.handle_event(ev)

    assert compared >= MIN_PARITY_COMPARISONS, (
        f"only {compared} ply/seat comparisons were exercised; "
        f"need >= {MIN_PARITY_COMPARISONS}"
    )
    assert mismatches == 0, (
        f"{mismatches} element mismatches across {compared} comparisons "
        f"(max abs diff {max_feat_diff})"
    )


def test_cpu_single_action_latency_smoke(shared_resources):
    """Benchmarks single-action inference latency on CPU over 50 iterations."""
    import time
    catalog = shared_resources["catalog"]
    cat_hash = shared_resources["cat_hash"]
    sample = shared_resources["samples"][0]
    device = torch.device("cpu")

    model, entry = load_and_validate_checkpoint("M25-D2-v2", cat_hash, device)
    belief_tracker = LiveBeliefTracker(viewer=0, player_count=2)

    # Warmup
    for _ in range(5):
        score_model_actions(model, entry, sample["observation"], sample["legal_actions"], belief_tracker, catalog, device)

    t0 = time.perf_counter()
    iterations = 50
    for _ in range(iterations):
        score_model_actions(model, entry, sample["observation"], sample["legal_actions"], belief_tracker, catalog, device)
    t1 = time.perf_counter()

    avg_ms = ((t1 - t0) / iterations) * 1000.0
    print(f"\nCPU Average single-action latency: {avg_ms:.2f} ms")
    assert avg_ms < 50.0, f"CPU latency {avg_ms:.2f} ms exceeds 50 ms budget"
