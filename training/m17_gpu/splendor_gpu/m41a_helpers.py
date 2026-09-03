"""M41A frozen helper contracts: the 16-epoch deterministic game
shuffle, the noncentral-t power inversion for the formal-test N, and
shared constants.

Everything here implements the frozen M41A design (docs/
m41a-counterfactual-action-value-probe.md, Revision 2, design SHA
c05d3fb): the exact seeds, the exact SplitMix64 key derivation, and
the exact minimum-integer power inversion. Any deviation is a design
amendment, not an implementation detail.
"""

from __future__ import annotations

import math
from typing import Callable

# --- Frozen identity ------------------------------------------------------

DESIGN_SHA = "c05d3fb"

# M41A seed namespace (design §4.1 / §2), disjoint from every prior
# family (M39A 40_260_xxx / 7_000_000 / 4M / 5.xM; M40A 8_xxx).
HEAD_INIT_SEED = 40_261_001
TRAINER_SEED = 40_261_002

# Source-game seed namespaces (design §2): formal corpus 9_0xx, pilot 9_1xx.
FORMAL_SEED_BASE = 9_000_000
PILOT_SEED_BASE = 9_100_000

# SplitMix64 key-derivation constants (design §4.1, frozen).
EPOCH_KEY_MIX = 0x9E3779B97F4A7C15
ORDINAL_KEY_MIX = 0xBF58476D1CE4E5B9

# The frozen A-head topology (design §4.1): q-head over the D2 joint
# representation z(o,a) = concat(s_emb, a_emb, s*a_emb), 3*192 -> 192 -> 1.
A_HEAD_INPUT_DIM = 576
A_HEAD_HIDDEN_DIM = 192


# --- The M41A 16-epoch deterministic game shuffle (design §4.1) -----------

def _splitmix64_mix(value: int) -> int:
    """The reviewed SplitMix64 mixing function (m39a_contract's mixer).

    Kept as an independent copy so this module has no runtime
    dependency on the M39A trainer module; the constants and operation
    order are identical and covered by an equivalence test.
    """
    z = value & 0xFFFFFFFFFFFFFFFF
    z = (z + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return z ^ (z >> 31)


def shuffle_key(epoch: int, game_ordinal: int) -> int:
    """key(e, g) = SplitMix64_mix(TRAINER_SEED xor (e*C1) xor (g*C2)).

    The exact derivation frozen by the design; supports any epoch
    count by construction (unlike M39A's shuffled_indices, which is
    hard-limited to epochs 1..4 and is explicitly NOT this mechanism).
    """
    mixed = (
        TRAINER_SEED
        ^ ((epoch * EPOCH_KEY_MIX) & 0xFFFFFFFFFFFFFFFF)
        ^ ((game_ordinal * ORDINAL_KEY_MIX) & 0xFFFFFFFFFFFFFFFF)
    )
    return _splitmix64_mix(mixed & 0xFFFFFFFFFFFFFFFF)


def epoch_game_order(num_games: int, epoch: int) -> list[int]:
    """The epoch's game sequence: sort ordinals by (key, ordinal).

    Deterministic, total (no ties possible — the ordinal is the
    tiebreak), and identical for both F/U arms by construction.
    """
    if num_games <= 0:
        return []
    if epoch < 1:
        raise ValueError("epoch must be >= 1")
    return sorted(range(num_games), key=lambda g: (shuffle_key(epoch, g), g))


# --- Noncentral-t power inversion (design §9.6) ----------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _t_cdf(t: float, df: int) -> float:
    """Central Student-t CDF via the regularized incomplete beta.

    P(T <= t) = 1 - 0.5 * I_{df/(df+t^2)}(df/2, 1/2)   (t > 0)
    (symmetric mirror for t < 0).
    """
    x = df / (df + t * t)
    a = df / 2.0
    b = 0.5
    tail = 0.5 * _betainc_reg(x, a, b)
    if t > 0:
        return 1.0 - tail
    return tail


def _betainc_reg(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b) via the continued-fraction
    Lentz algorithm (Numerical Recipes 6.4). Accurate to ~1e-14 for
    the df/effect ranges M41A uses; independently tested against
    known critical values in the module tests.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(x, a, b) / a
    return 1.0 - front * _betacf(1.0 - x, b, a) / b


def _betacf(x: float, a: float, b: float, itmax: int = 300, eps: float = 3e-16) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _chi2_ppf(p: float, df: int) -> float:
    """Chi-square quantile via bisection on the regularized incomplete
    gamma P(df/2, x/2) (self-contained; no scipy dependency).

    P(a, x) = I_{x/(x+... )}: for the chi-square, CDF(u) =
    gammainc_lower(df/2, u/2) = 1 - I_{df/2}(u/2 ... ) — computed here
    through the regularized incomplete beta identity on the
    EVEN/ODD df is unnecessary; instead we integrate the closed
    relation CDF(u) = I_{u/(u+2), df/2, 1/2}? No — the chi-square CDF
    is the regularized LOWER incomplete gamma, for which the
    continued-fraction evaluation below (Numerical Recipes 6.2) is
    used directly.
    """
    a = df / 2.0
    target = p
    lo, hi = 0.0, 1.0
    while _gammainc_lower(a, hi / 2.0) < target:
        hi *= 2.0
        if hi > 1e12:
            break
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if _gammainc_lower(a, mid / 2.0) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _gammainc_lower(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) (NR 6.2)."""
    if x <= 0.0:
        return 0.0
    if x < a + 1.0:
        # Series.
        ap = a
        summ = 1.0 / a
        delt = summ
        for _ in range(1000):
            ap += 1.0
            delt *= x / ap
            summ += delt
            if abs(delt) < abs(summ) * 1e-16:
                break
        return summ * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # Continued fraction for Q, then P = 1 - Q.
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


_GL_NODES_128: list[tuple[float, float]] | None = None


def _gauss_legendre_128() -> list[tuple[float, float]]:
    """Gauss-Legendre nodes/weights on (-1, 1), 128 points (computed by
    Newton iteration on the Legendre recurrence; cached)."""
    global _GL_NODES_128
    if _GL_NODES_128 is not None:
        return _GL_NODES_128
    n = 128
    nodes = []
    for i in range(1, n + 1):
        # Initial guess (Chebyshev-like).
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, x
            for k in range(2, n + 1):
                p2 = ((2 * k - 1) * x * p1 - (k - 1) * p0) / k
                p0, p1 = p1, p2
            dp = n * (x * p1 - p0) / (x * x - 1.0)
            dx = p1 / dp
            x -= dx
            if abs(dx) < 1e-15:
                break
        w = 2.0 / ((1.0 - x * x) * dp * dp)
        nodes.append((x, w))
    _GL_NODES_128 = nodes
    return nodes


def _noncentral_t_cdf_bk(t: float, df: int, ncp: float) -> float:
    """Noncentral-t CDF P(T' <= t), T' = (Z + ncp) / sqrt(V/df).

    Exact conditional decomposition: given V = v (chi-square, df),
    T' <= t  <=>  Z <= t*sqrt(v/df) - ncp, so

        P(T' <= t) = E_V[ Phi(t*sqrt(V/df) - ncp) ],

    evaluated by 128-point Gauss-Legendre quadrature over the chi-square
    quantile transform (p in (0,1), v = chi2_ppf(p, df)). Validated
    against scipy.stats.nct to < 1e-7 across the M41A grid (tests).
    """
    if df <= 0:
        raise ValueError("df must be positive")
    if abs(ncp) < 1e-300:
        return _t_cdf(t, df)
    total = 0.0
    for x, w in _gauss_legendre_128():
        p = 0.5 * (x + 1.0)
        # Guard the extreme tails where the ppf saturates.
        if p < 1e-12 or p > 1.0 - 1e-12:
            continue
        v = _chi2_ppf(p, df)
        total += w * _normal_cdf(t * math.sqrt(v / df) - ncp)
    return min(1.0, max(0.0, 0.5 * total))


def one_sided_t_power(n: int, sd: float, effect: float, alpha: float = 0.025) -> float:
    """Power of the one-sample one-sided Student-t test of H0: mu=0
    against true mean `effect`, with sample SD `sd`, at level `alpha`.

    power(n) = P(T' > t_crit) under noncentrality effect*sqrt(n)/sd,
    with t_crit the one-sided central-t critical value at df = n-1.
    """
    df = n - 1
    if df < 1 or sd <= 0:
        raise ValueError("n must be >= 2 and sd > 0")
    tcrit = t_critical_one_sided(alpha, df)
    ncp = effect * math.sqrt(n) / sd
    return 1.0 - _noncentral_t_cdf_bk(tcrit, df, ncp)


def t_critical_one_sided(alpha: float, df: int) -> float:
    """The one-sided central-t critical value t_alpha(df), by bisection
    on the central-t CDF."""
    if not 0.0 < alpha < 0.5:
        raise ValueError("alpha must be in (0, 0.5) for one-sided")
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if 1.0 - _t_cdf(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def minimum_formal_n(
    sd: float,
    effect: float = 0.03,
    alpha: float = 0.025,
    power: float = 0.90,
    upper_bound: int = 100_000,
) -> int:
    """The MINIMUM integer N with one-sample one-sided Student-t power
    >= `power` (design §9.6): monotone integer bisection over N.

    The z-formula ceil(((z_{1-a}+z_{1-b})*sd/effect)^2) may be used by
    callers only as a cross-check; THIS function's output is the frozen
    N (the design names the noncentral-t inversion as authoritative).
    """
    if sd <= 0:
        raise ValueError("sd must be > 0")
    if effect <= 0:
        raise ValueError("effect must be > 0")

    def ok(n: int) -> bool:
        return one_sided_t_power(n, sd, effect, alpha) >= power

    if ok(2):
        return 2
    lo, hi = 2, None
    # Exponential bracket.
    n = 4
    while n <= upper_bound:
        if ok(n):
            hi = n
            break
        lo = n
        n *= 2
    if hi is None:
        raise ValueError(
            f"no N <= {upper_bound} reaches power {power}; the design's "
            "STOP rule applies (N beyond availability)"
        )
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def z_formula_n(sd: float, effect: float = 0.03, alpha: float = 0.025, power: float = 0.90) -> int:
    """The z-approximation N — CROSS-CHECK ONLY (design §9.6: the
    noncentral-t minimum is the frozen N; this is a bracket/sanity
    value, never the reported N)."""
    from statistics import NormalDist

    z_alpha = NormalDist().inv_cdf(1 - alpha)
    z_beta = NormalDist().inv_cdf(power)
    return math.ceil(((z_alpha + z_beta) * sd / effect) ** 2)
