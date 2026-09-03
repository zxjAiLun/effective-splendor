"""M41A helper contract tests: the frozen 16-epoch shuffle, the
t/noncentral-t machinery, and the minimum-N power inversion.

The critical-value cross-checks pin the incomplete-beta implementation
against the M40A frozen constants (which were themselves independently
adjudicated); the noncentral-t CDF is validated against scipy where
available (skipped, not weakened, otherwise).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu import m41a_helpers as h


# ---------------------------------------------------------------------------
# Shuffle contract (design §4.1)
# ---------------------------------------------------------------------------


def test_shuffle_constants_frozen():
    assert h.HEAD_INIT_SEED == 40_261_001
    assert h.TRAINER_SEED == 40_261_002
    assert h.EPOCH_KEY_MIX == 0x9E3779B97F4A7C15
    assert h.ORDINAL_KEY_MIX == 0xBF58476D1CE4E5B9


def test_shuffle_is_permation_and_deterministic():
    order = h.epoch_game_order(512, 1)
    assert sorted(order) == list(range(512))
    assert h.epoch_game_order(512, 1) == order


def test_shuffle_supports_epochs_1_to_16_and_beyond():
    orders = {e: h.epoch_game_order(100, e) for e in range(1, 17)}
    for e, order in orders.items():
        assert sorted(order) == list(range(100))
    # All 16 epochs are distinct orderings.
    distinct = {tuple(o) for o in orders.values()}
    assert len(distinct) == 16


def test_shuffle_differs_from_m39a_shuffled_indices():
    """M41A's shuffle is its own mechanism — for the overlapping epoch
    range it must NOT coincidentally equal the M39A helper's order."""
    from splendor_gpu.m39a_contract import shuffled_indices

    m41a = h.epoch_game_order(100, 1)
    m39a = shuffled_indices(100, 1, 1)
    assert m41a != m39a, "M41A must not reuse the M39A epoch-1 order"


def test_splitmix64_matches_m39a_mixer():
    """The mixer function itself is the reviewed m39a_contract one."""
    from splendor_gpu.m39a_contract import splitmix64

    for value in (0, 1, 42, 40_261_002, 2**64 - 1):
        assert h._splitmix64_mix(value) == splitmix64(value)


# ---------------------------------------------------------------------------
# t critical values (pin against the M40A frozen constants)
# ---------------------------------------------------------------------------


def test_t_critical_matches_m40a_frozen_constants():
    # M40A H1: one-sided 95% at df=127.
    assert h.t_critical_one_sided(0.05, 127) == pytest.approx(
        1.656940343542, abs=1e-9
    )
    # M40A league: one-sided 95% at df=31.
    assert h.t_critical_one_sided(0.05, 31) == pytest.approx(
        1.695518782546, abs=1e-9
    )
    # M40A anchor: two-sided 95% at df=63 == one-sided 97.5%.
    assert h.t_critical_one_sided(0.025, 63) == pytest.approx(
        1.998340542521, abs=1e-9
    )


def test_t_cdf_symmetry_and_limits():
    assert h._t_cdf(0.0, 100) == pytest.approx(0.5)
    assert h._t_cdf(1e9, 100) == pytest.approx(1.0)
    assert h._t_cdf(-1e9, 100) == pytest.approx(0.0)
    assert h._t_cdf(2.0, 100) == pytest.approx(1.0 - h._t_cdf(-2.0, 100))


# ---------------------------------------------------------------------------
# Noncentral-t CDF
# ---------------------------------------------------------------------------


def test_noncentral_t_degrades_to_central_at_zero_ncp():
    tc = h.t_critical_one_sided(0.025, 127)
    assert h._noncentral_t_cdf_bk(tc, 127, 0.0) == pytest.approx(0.975, abs=1e-9)


def test_noncentral_t_monotone_in_ncp():
    """CDF at a fixed positive threshold is DECREASING in ncp (higher
    noncentrality pushes mass past the threshold)."""
    tc = h.t_critical_one_sided(0.025, 63)
    values = [h._noncentral_t_cdf_bk(tc, 63, ncp) for ncp in (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0)]
    assert values == sorted(values, reverse=True)


def test_noncentral_t_against_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    nct = scipy_stats.nct
    max_err = 0.0
    for df in (31, 63, 127, 255):
        tc = h.t_critical_one_sided(0.025, df)
        for ncp in (0.5, 1.0, 2.0, 3.0, 5.0):
            got = h._noncentral_t_cdf_bk(tc, df, ncp)
            want = nct.cdf(tc, df, ncp)
            max_err = max(max_err, abs(got - want))
    assert max_err < 1e-6


# ---------------------------------------------------------------------------
# Power and the minimum-N inversion (design §9.6)
# ---------------------------------------------------------------------------


def test_power_at_ncp_zero_equals_alpha():
    for n in (32, 128, 512):
        alpha = 0.025
        p = h.one_sided_t_power(n, sd=0.30, effect=1e-12, alpha=alpha)
        # effect ~ 0 => power ~ alpha (exactly alpha in the limit).
        assert p == pytest.approx(alpha, abs=1e-3)


def test_power_increases_with_effect_and_n():
    p_small = h.one_sided_t_power(100, 0.30, 0.03)
    p_large = h.one_sided_t_power(100, 0.30, 0.06)
    assert p_large > p_small
    p_n_small = h.one_sided_t_power(50, 0.30, 0.03)
    p_n_large = h.one_sided_t_power(200, 0.30, 0.03)
    assert p_n_large > p_n_small


def test_minimum_formal_n_is_minimal():
    n = h.minimum_formal_n(sd=0.25)
    assert h.one_sided_t_power(n, 0.25, 0.03) >= 0.90
    assert h.one_sided_t_power(n - 1, 0.25, 0.03) < 0.90


def test_minimum_formal_n_brackets_z_formula():
    """The z-approximation must be within a few percent of the exact
    noncentral-t N (it is the cross-check, never the authority)."""
    for sd in (0.10, 0.25, 0.40):
        n_exact = h.minimum_formal_n(sd=sd)
        n_z = h.z_formula_n(sd=sd)
        assert abs(n_exact - n_z) <= max(8, 0.02 * n_z)


def test_minimum_formal_n_raises_beyond_bound():
    with pytest.raises(ValueError, match="STOP"):
        # An absurdly small upper bound forces the design's STOP path.
        h.minimum_formal_n(sd=10.0, upper_bound=8)


def test_formal_effect_scale_is_bps_consistent():
    """+300 bps = 0.03 in centered-return units: the design's effect."""
    assert h.minimum_formal_n(sd=0.25, effect=0.03) == h.minimum_formal_n(
        sd=0.25, effect=300 / 10_000
    )
