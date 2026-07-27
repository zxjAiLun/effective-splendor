//! A stable, seed-only pseudo-random generator (xorshift64\*).
//!
//! The algorithm and the seed-initialization constant are frozen and covered by
//! the `rng_is_frozen` test. Do not change them: a change would silently alter
//! every reference-agent transcript. This RNG is the agent's own action-selection
//! RNG (never the engine's setup RNG), and it deliberately does not depend on the
//! `rand` crate, so the same seed and server transcript always select the same
//! actions, byte-for-byte, on every platform.

/// A stable, seed-only pseudo-random generator (xorshift64\*).
///
/// The algorithm and the seed-initialization constant are frozen and covered by
/// [`tests::rng_is_frozen`]. Do not change them: a change would silently alter
/// every reference-agent transcript.
#[derive(Debug, Clone)]
pub struct StableRng(u64);

impl StableRng {
    /// Odd dispersal constant (fractional bits of the golden ratio). Mixing the
    /// raw seed with this and OR-ing in the low bit guarantees the xorshift
    /// state is never the forbidden all-zero fixed point — in particular
    /// `StableRng::new(0)` is well-behaved.
    const SEED_INIT: u64 = 0x9E37_79B9_7F4A_7C15;

    /// Multiplier of the `*` (star) output stage.
    const MULTIPLIER: u64 = 0x2545_F491_4F6C_DD1D;

    /// Seed the generator. Any `u64` seed (including 0) yields a valid,
    /// non-degenerate state.
    pub fn new(seed: u64) -> Self {
        StableRng((seed ^ Self::SEED_INIT) | 1)
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(Self::MULTIPLIER)
    }

    /// A uniformly distributed index in `[0, len)` using rejection sampling to
    /// avoid the modulo bias a bare `next_u64() % len` would introduce.
    ///
    /// This is the **public, stable** sampling entry point of the SDK: an
    /// external `AgentPolicy` selects a legal action via
    /// `context.rng.index(len)`. The algorithm, seed-init constant, and output
    /// sequence are frozen (see the `rng_is_frozen` test); changing any of them
    /// would alter every reference transcript, so do not modify it.
    ///
    /// Panics if `len == 0`; callers must guarantee a non-empty range.
    pub fn index(&mut self, len: usize) -> usize {
        assert!(len > 0, "index range must be non-empty");
        let len = len as u64;
        // `2^64 mod len`: the size of the biased tail we must reject so the
        // accepted region is an exact multiple of `len`.
        let reject_below = (0u64.wrapping_sub(len)) % len;
        loop {
            let v = self.next_u64();
            if v >= reject_below {
                return (v % len) as usize;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The xorshift64\* algorithm and seed-init constant are frozen. If this
    /// ever fails, the reference agent's transcripts changed — do not "fix" the
    /// expectations, revert the algorithm change.
    #[test]
    fn rng_is_frozen() {
        let mut r0 = StableRng::new(0);
        assert_eq!(
            [r0.next_u64(), r0.next_u64(), r0.next_u64(), r0.next_u64()],
            [
                0x0D83_B3E2_9A21_487A,
                0x54C4_4C79_F1FE_9D67,
                0xA845_F342_007A_0E78,
                0x7D6E_0B87_8A79_4779,
            ]
        );
        let mut r42 = StableRng::new(42);
        assert_eq!(
            [
                r42.next_u64(),
                r42.next_u64(),
                r42.next_u64(),
                r42.next_u64()
            ],
            [
                0x0832_8D7F_03BC_EC1A,
                0x077E_7279_E17A_B6CD,
                0x0C4E_098F_541B_B09E,
                0xD861_FCF4_7B8B_124E,
            ]
        );
    }

    #[test]
    fn seed_zero_is_not_degenerate() {
        let mut r = StableRng::new(0);
        // A degenerate all-zero state would emit only zeros forever.
        assert!((0..8).any(|_| r.next_u64() != 0));
    }

    #[test]
    fn index_is_always_in_range() {
        let mut r = StableRng::new(7);
        for len in 1..=32usize {
            for _ in 0..64 {
                assert!(r.index(len) < len);
            }
        }
    }
}
