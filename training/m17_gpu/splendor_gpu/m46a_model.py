"""M46A frozen architecture: Relational Successor Scorer (exact DESIGN V2).

Topology (frozen, no alternatives):
  CARD_RELATION_MLP:   39 -> 128 -> GELU -> 128 -> GELU
  NOBLE_RELATION_MLP:  12 -> 128 -> GELU -> 128 -> GELU
  PLAYER_RAW_MLP:      26 -> 128 -> GELU -> 128
  GLOBAL_RAW_MLP:      13 -> 64  -> GELU -> 64
  per scored player: card SUM(128) + card MAX(128) + noble SUM(128)
                     + noble MAX(128) + player(128) + global(64) = 704
  head: Linear(704,256) -> GELU -> Linear(256,128) -> GELU
        -> 2 x ResidualBlock(128) [y = x + W2(GELU(W1(x)))] -> LayerNorm
  progress head: Linear(128,1)
  mechanics heads (single linear maps, no hidden layers):
    card summary (256)  -> affordable count (16), max prestige (6)
    noble summary (256) -> claimable nobles (6), min deficit (21)

Both players share all scorer parameters. Masked MAX over an empty set
returns the zero vector. No attention, no learned pooling, no dropout,
no action encoder, no hidden architecture choice.
"""

import torch
import torch.nn as nn

CARD_IN, NOBLE_IN, PLAYER_IN, GLOBAL_IN = 39, 12, 26, 13


class M46AResidualBlock(nn.Module):
    """y = x + W2(GELU(W1(x))). No norm, no activation outside, no dropout."""

    def __init__(self, dim: int = 128):
        super().__init__()
        self.w1 = nn.Linear(dim, dim)
        self.w2 = nn.Linear(dim, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.w2(torch.nn.functional.gelu(self.w1(x)))


class RelationalSuccessorScorer(nn.Module):
    def __init__(self):
        super().__init__()
        self.card_mlp = nn.Sequential(
            nn.Linear(CARD_IN, 128), nn.GELU(), nn.Linear(128, 128), nn.GELU(),
        )
        self.noble_mlp = nn.Sequential(
            nn.Linear(NOBLE_IN, 128), nn.GELU(), nn.Linear(128, 128), nn.GELU(),
        )
        self.player_mlp = nn.Sequential(
            nn.Linear(PLAYER_IN, 128), nn.GELU(), nn.Linear(128, 128),
        )
        self.global_mlp = nn.Sequential(
            nn.Linear(GLOBAL_IN, 64), nn.GELU(), nn.Linear(64, 64),
        )
        self.head = nn.Sequential(
            nn.Linear(704, 256), nn.GELU(), nn.Linear(256, 128), nn.GELU(),
        )
        self.blocks = nn.Sequential(M46AResidualBlock(128), M46AResidualBlock(128))
        self.norm = nn.LayerNorm(128, elementwise_affine=True, eps=1e-5)
        self.progress = nn.Linear(128, 1)
        self.aff_count = nn.Linear(256, 16)
        self.aff_max = nn.Linear(256, 6)
        self.noble_claim = nn.Linear(256, 6)
        self.noble_mindef = nn.Linear(256, 21)

    def encode(
        self,
        card: torch.Tensor,      # (..., C, 39) float
        card_mask: torch.Tensor,  # (..., C) bool
        noble: torch.Tensor,     # (..., N, 12) float
        noble_mask: torch.Tensor,  # (..., N) bool
        praw: torch.Tensor,      # (..., 26) float
        glob: torch.Tensor,      # (..., 13) float
    ) -> dict:
        ce = self.card_mlp(card)  # (..., C, 128)
        m = card_mask.unsqueeze(-1)
        card_sum = (ce * m).sum(dim=-2)
        neg_inf = torch.finfo(ce.dtype).min
        card_max = ce.masked_fill(~m, neg_inf).amax(dim=-2)
        card_max = torch.where(m.any(dim=-1, keepdim=True).expand_as(card_max),
                               card_max, torch.zeros_like(card_max))
        ne = self.noble_mlp(noble)
        nm = noble_mask.unsqueeze(-1)
        noble_sum = (ne * nm).sum(dim=-2)
        noble_max = ne.masked_fill(~nm, neg_inf).amax(dim=-2)
        noble_max = torch.where(nm.any(dim=-1, keepdim=True).expand_as(noble_max),
                                noble_max, torch.zeros_like(noble_max))
        pe = self.player_mlp(praw)
        ge = self.global_mlp(glob)
        card_summary = torch.cat([card_sum, card_max], dim=-1)
        noble_summary = torch.cat([noble_sum, noble_max], dim=-1)
        h = torch.cat([card_summary, noble_summary, pe, ge], dim=-1)
        h = self.norm(self.blocks(self.head(h)))
        return {
            "rep": h,
            "progress": self.progress(h).squeeze(-1),
            "card_summary": card_summary,
            "noble_summary": noble_summary,
            "aff_count": self.aff_count(card_summary),
            "aff_max": self.aff_max(card_summary),
            "noble_claim": self.noble_claim(noble_summary),
            "noble_mindef": self.noble_mindef(noble_summary),
        }
