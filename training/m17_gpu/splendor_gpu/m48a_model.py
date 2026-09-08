"""M48A residual model: M46A trunk reuse + zero-init residual head.

DESIGN_V2 contract:
- Trunk = M46A RelationalSuccessorScorer encoders (card/noble/player/global
  MLPs, SUM+MAX aggregation, 704->256->128, 2 residual blocks, LayerNorm).
- NO mechanics heads, NO progress head, NO action encoder, NO attention.
- Fresh random init under the training seed (no M46A checkpoint loading).
- Single residual head Linear(128,1) with weight=0 and bias=0 EXACTLY,
  so r_theta(a) == 0 for all actions at init (G0 bit-exact n1 equality).
- Viewer-relative residual u = h(s,p) - h(s,1-p); action residual
  r(a) = mean over 4 successors; terminal successors contribute u = 0.
"""

import torch
import torch.nn as nn

from splendor_gpu.m46a_model import M46AResidualBlock

CARD_IN, NOBLE_IN, PLAYER_IN, GLOBAL_IN = 39, 12, 26, 13


class ResidualSuccessorNet(nn.Module):
    """M46A trunk family with a single zero-initialized residual head."""

    def __init__(self):
        super().__init__()
        # Trunk (identical topology to M46A RelationalSuccessorScorer).
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
        # Residual head: EXACTLY zero weight and bias (contract B2/G0).
        self.residual = nn.Linear(128, 1)
        with torch.no_grad():
            self.residual.weight.zero_()
            self.residual.bias.zero_()

    def encode(self, card, card_mask, noble, noble_mask, praw, glob):
        ce = self.card_mlp(card)
        m = card_mask.unsqueeze(-1)
        card_sum = (ce * m).sum(dim=-2)
        neg_inf = torch.finfo(ce.dtype).min
        card_max = ce.masked_fill(~m, neg_inf).amax(dim=-2)
        card_max = torch.where(m.any(dim=-2).expand_as(card_max),
                               card_max, torch.zeros_like(card_max))
        ne = self.noble_mlp(noble)
        nm = noble_mask.unsqueeze(-1)
        noble_sum = (ne * nm).sum(dim=-2)
        noble_max = ne.masked_fill(~nm, neg_inf).amax(dim=-2)
        noble_max = torch.where(nm.any(dim=-2).expand_as(noble_max),
                                noble_max, torch.zeros_like(noble_max))
        pe = self.player_mlp(praw)
        ge = self.global_mlp(glob)
        h = torch.cat([card_sum, card_max, noble_sum, noble_max, pe, ge], dim=-1)
        return self.norm(self.blocks(self.head(h)))

    def viewer_residual(self, card, card_mask, noble, noble_mask, praw, glob):
        """u_theta(s,p) = h(s,p) - h(s,1-p); input batch is (..., P, feat)
        with P=2 players per successor."""
        h = self.encode(card, card_mask, noble, noble_mask, praw, glob)
        return h[..., 0, :] - h[..., 1, :]

    def assert_zero_init(self):
        """G0 precondition: residual head still exactly zero."""
        with torch.no_grad():
            if not torch.all(self.residual.weight == 0):
                return False
            if not torch.all(self.residual.bias == 0):
                return False
        return True
