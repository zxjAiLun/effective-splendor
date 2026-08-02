//! Frozen deterministic RNG for C2 sampling (M07).
//!
//! The platform and library `rand` shuffles are intentionally not used: their
//! algorithm and output are not stable across versions. Instead, the sampler
//! uses a SHA-256 counter stream:
//!
//! ```text
//! domain       = "effective-splendor-determinization-rng-v1\0"
//! key material = information_set_hash ASCII
//!                || sample_seed little-endian
//!                || sample_index little-endian
//! block(c)     = SHA-256(domain || key_material || c little-endian)
//! ```
//!
//! `u64` values are read little-endian from each block in fixed order.
//! [`DeterministicRng::draw_below`] uses rejection sampling so no modulo bias
//! is introduced.

use sha2::{Digest, Sha256};

/// Frozen RNG domain separator (trailing NUL is part of the domain).
pub(crate) const DETERMINIZATION_RNG_DOMAIN: &str = "effective-splendor-determinization-rng-v1\0";

const U64S_PER_BLOCK: usize = 4;

/// SHA-256 counter stream producing `u64` little-endian values.
pub(crate) struct DeterministicRng {
    key_material: Vec<u8>,
    counter: u64,
    buffer: [u8; 32],
    buf_pos: usize,
    #[cfg(test)]
    injected_blocks: Option<std::vec::IntoIter<[u8; 32]>>,
}

impl DeterministicRng {
    /// Create a stream from the frozen key material.
    pub(crate) fn new(key_material: Vec<u8>) -> Self {
        let mut rng = Self {
            key_material,
            counter: 0,
            buffer: [0u8; 32],
            buf_pos: U64S_PER_BLOCK, // force a refill on first next_u64
            #[cfg(test)]
            injected_blocks: None,
        };
        rng.refill();
        rng
    }

    /// Test-only constructor: seed the buffer with raw blocks so rejection
    /// paths can be exercised deterministically.
    #[cfg(test)]
    fn from_blocks(blocks: Vec<[u8; 32]>) -> Self {
        let mut blocks = blocks.into_iter();
        let buffer = blocks.next().expect("at least one injected block");
        Self {
            key_material: Vec::new(),
            counter: 0,
            buffer,
            buf_pos: 0,
            injected_blocks: Some(blocks),
        }
    }

    fn refill(&mut self) {
        #[cfg(test)]
        {
            let injected = self
                .injected_blocks
                .as_mut()
                .and_then(std::iter::Iterator::next);
            if let Some(block) = injected {
                self.buffer = block;
                self.buf_pos = 0;
                return;
            }
            self.injected_blocks = None;
        }

        let mut hasher = Sha256::new();
        hasher.update(DETERMINIZATION_RNG_DOMAIN.as_bytes());
        hasher.update(&self.key_material);
        hasher.update(self.counter.to_le_bytes());
        self.buffer = hasher.finalize().into();
        self.counter += 1;
        self.buf_pos = 0;
    }

    /// Next `u64` from the stream, little-endian, in frozen order.
    pub(crate) fn next_u64(&mut self) -> u64 {
        if self.buf_pos >= U64S_PER_BLOCK {
            self.refill();
        }
        let start = self.buf_pos * 8;
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&self.buffer[start..start + 8]);
        self.buf_pos += 1;
        u64::from_le_bytes(bytes)
    }

    /// Uniform integer in `[0, n)` via rejection sampling (no modulo bias).
    /// `n == 0` is unreachable in the frozen call sites (Fisher-Yates steps
    /// draw `i + 1 >= 2`, deck draws draw non-empty decks).
    pub(crate) fn draw_below(&mut self, n: u64) -> u64 {
        debug_assert!(n > 0);
        if n == 1 {
            return 0;
        }
        // Largest multiple of n not exceeding u64::MAX.
        let limit = u64::MAX - (u64::MAX % n);
        loop {
            let v = self.next_u64();
            if v < limit {
                return v % n;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frozen_stream_sequence() {
        let mut rng = DeterministicRng::new(b"frozen-key".to_vec());
        let values: Vec<u64> = (0..8).map(|_| rng.next_u64()).collect();
        // Frozen values for key "frozen-key" under the domain/counter/LE
        // contract documented above.
        let golden = [
            0x9AA564EAC794A88Bu64,
            0x53AA926EA352A349u64,
            0x6A6EB7DBC660FD69u64,
            0xF1E4E4029C328C3Bu64,
            0x97183C0108D73617u64,
            0x846E7823BA861541u64,
            0xFF0FC0C1E6F0578Au64,
            0xE4CFECB1C749872Fu64,
        ];
        assert_eq!(values, golden);
    }

    #[test]
    fn draw_below_is_bounded() {
        let mut rng = DeterministicRng::new(b"draw-test".to_vec());
        for n in [2u64, 3, 5, 7, 13, 100, 1_000_003] {
            for _ in 0..200 {
                assert!(rng.draw_below(n) < n);
            }
        }
    }

    #[test]
    fn draw_below_rejection_path_is_handled() {
        // A block of all 0xFF yields u64::MAX for every u64 slot; with
        // n = 4, limit = u64::MAX - 3, so u64::MAX must be rejected and the
        // next block must be used. The second block is crafted so the first
        // u64 is 2, giving draw_below(4) == 2.
        let mut rng = DeterministicRng::from_blocks(vec![
            [0xFFu8; 32],
            [
                2u8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0,
            ],
        ]);
        assert_eq!(rng.draw_below(4), 2);
        // With n = 2, limit = u64::MAX - 1; the crafted value 2 is accepted.
        let mut rng = DeterministicRng::from_blocks(vec![[
            2u8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0,
        ]]);
        assert_eq!(rng.draw_below(2), 0);
    }

    #[test]
    fn draw_below_one_is_trivial() {
        let mut rng = DeterministicRng::new(b"one-test".to_vec());
        assert_eq!(rng.draw_below(1), 0);
        assert_eq!(rng.draw_below(1), 0);
    }
}
