"""M29A-v2 Architecture: Nested Residual Action-Conditioned Entity Attention (h192/b4 + D2 baseline + zero-init residual attention logit)."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from splendor_gpu.model import ResidualBlock
from splendor_gpu.encoding import ENTITY_FEATURES, GLOBAL_FEATURES

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class NestedResidualActionEntityMixer(nn.Module):
    """M29A-v2 Nested Residual Attention Model.

    Preserves exact D2 module order and exact D2 policy scoring path [state, action, state * action],
    while adding an attention residual path with zero-initialized final projection.
    At initialization, forward outputs are strictly mathematically identical to D2 baseline.
    """

    def __init__(self, hidden_dim=192, blocks=4, dropout=0.0):
        super().__init__()
        h = hidden_dim
        self.hidden_dim = h

        # --- Exact D2 Module Initialization Order ---
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, dropout) for _ in range(blocks)))
        self.norm = nn.LayerNorm(h)

        self.action_encoder = nn.Sequential(nn.Linear(ENHANCED_ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.policy = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, 1))
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

        # --- Nested Residual Attention Path ---
        self.action_query_proj = nn.Linear(h, h)
        self.entity_key_proj = nn.Linear(h, h)
        self.entity_val_proj = nn.Linear(h, h)

        # Residual scorer: consumes queried entity context interacting with action and state
        self.attn_residual_head = nn.Sequential(
            nn.Linear(h * 4, h),
            nn.GELU(),
            nn.Linear(h, 1, bias=False)  # Final linear projection zero-initialized
        )
        # Zero-initialize the final projection weight so initial residual is strictly 0
        nn.init.zeros_(self.attn_residual_head[2].weight)

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor):
        encoded_entities = self.entity_encoder(entities)
        gate = self.entity_gate(encoded_entities).squeeze(-1).masked_fill(~mask, torch.finfo(encoded_entities.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded_entities * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        state = self.norm(self.blocks(state))
        return state, encoded_entities

    def compute_attention_residual(
        self,
        expanded_state: torch.Tensor,     # (total_actions, h)
        expanded_entities: torch.Tensor,  # (total_actions, N, h)
        expanded_mask: torch.Tensor,      # (total_actions, N)
        action_emb: torch.Tensor,         # (total_actions, h)
    ) -> torch.Tensor:
        Q = self.action_query_proj(action_emb).unsqueeze(1)  # (total_actions, 1, h)
        K = self.entity_key_proj(expanded_entities)          # (total_actions, N, h)
        V = self.entity_val_proj(expanded_entities)          # (total_actions, N, h)

        scores = torch.bmm(Q, K.transpose(1, 2)).squeeze(1) / (self.hidden_dim ** 0.5)  # (total_actions, N)
        scores = scores.masked_fill(~expanded_mask, torch.finfo(scores.dtype).min)
        attn_weights = torch.softmax(scores, dim=-1).unsqueeze(1)  # (total_actions, 1, N)

        queried_context = torch.bmm(attn_weights, V).squeeze(1)  # (total_actions, h)

        residual_input = torch.cat([
            expanded_state,
            action_emb,
            queried_context,
            action_emb * queried_context,
        ], dim=-1)  # (total_actions, 4*h)

        return self.attn_residual_head(residual_input).squeeze(-1)  # (total_actions,)

    def forward_packed(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        action_offsets: torch.Tensor,
    ):
        state, encoded_entities = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded_state = torch.repeat_interleave(state, counts, dim=0)

        # Baseline D2 Logits: exact [expanded_state, action, expanded_state * action]
        base_logits = self.policy(torch.cat([expanded_state, action, expanded_state * action], dim=-1)).squeeze(-1)

        # Residual Attention Logits
        expanded_entities = torch.repeat_interleave(encoded_entities, counts, dim=0)
        expanded_mask = torch.repeat_interleave(mask, counts, dim=0)
        residual_logits = self.compute_attention_residual(expanded_state, expanded_entities, expanded_mask, action)

        logits = base_logits + residual_logits
        return logits, self.value(state)
