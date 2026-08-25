"""M29A Architecture: Action-Conditioned Entity Pooling v1 (h192/b4 + D2 delta + action query attention)."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from splendor_gpu.model import ResidualBlock
from splendor_gpu.encoding import ENTITY_FEATURES, GLOBAL_FEATURES

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class ActionConditionedEntityMixer(nn.Module):
    def __init__(self, hidden_dim=192, blocks=4, dropout=0.0):
        super().__init__()
        h = hidden_dim
        self.hidden_dim = h

        # 1. State / Entity Encoders (same as baseline EntityMixer)
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, dropout) for _ in range(blocks)))
        self.norm = nn.LayerNorm(h)

        # 2. Value Head (conditioned on global state embedding)
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

        # 3. Action Encoder (59-dim -> h)
        self.action_encoder = nn.Sequential(nn.Linear(ENHANCED_ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))

        # 4. Action-Conditioned Cross-Attention / Entity Query Layer
        # Action queries the encoded entity sequence to pool the most relevant entity features for THIS action.
        self.action_query_proj = nn.Linear(h, h)
        self.entity_key_proj = nn.Linear(h, h)
        self.entity_val_proj = nn.Linear(h, h)
        self.action_entity_mix = nn.Linear(h * 2, h)

        # 5. Policy Head: combines global state, action-queried entity context, and action embedding
        # Input dimension: state (h) + action_conditioned_context (h) + action (h) + interaction terms
        self.policy = nn.Sequential(
            nn.Linear(h * 4, h),
            nn.GELU(),
            nn.Linear(h, 1)
        )

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor):
        encoded_entities = self.entity_encoder(entities)  # (B, N, h)
        gate = self.entity_gate(encoded_entities).squeeze(-1).masked_fill(~mask, torch.finfo(encoded_entities.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded_entities * weights).sum(dim=1)  # (B, h)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        state = self.norm(self.blocks(state))  # (B, h)
        return state, encoded_entities

    def forward_packed(
        self,
        entities: torch.Tensor,          # (B, N, ENTITY_FEATURES)
        mask: torch.Tensor,              # (B, N)
        global_features: torch.Tensor,   # (B, GLOBAL_FEATURES)
        actions: torch.Tensor,           # (total_actions, ENHANCED_ACTION_FEATURES)
        action_offsets: torch.Tensor,    # (B + 1,)
    ):
        B = entities.shape[0]
        state, encoded_entities = self.state_embedding(entities, mask, global_features) # (B, h), (B, N, h)

        action_emb = self.action_encoder(actions) # (total_actions, h)
        counts = action_offsets[1:] - action_offsets[:-1]

        # Expand state and encoded_entities to match packed action batch
        expanded_state = torch.repeat_interleave(state, counts, dim=0) # (total_actions, h)
        expanded_entities = torch.repeat_interleave(encoded_entities, counts, dim=0) # (total_actions, N, h)
        expanded_mask = torch.repeat_interleave(mask, counts, dim=0) # (total_actions, N)

        # Action Query Cross-Attention over Entities:
        # Query: Q = action_query_proj(action_emb) -> (total_actions, 1, h)
        # Key: K = entity_key_proj(expanded_entities) -> (total_actions, N, h)
        # Value: V = entity_val_proj(expanded_entities) -> (total_actions, N, h)
        Q = self.action_query_proj(action_emb).unsqueeze(1) # (total_actions, 1, h)
        K = self.entity_key_proj(expanded_entities) # (total_actions, N, h)
        V = self.entity_val_proj(expanded_entities) # (total_actions, N, h)

        scores = torch.bmm(Q, K.transpose(1, 2)).squeeze(1) / (self.hidden_dim ** 0.5) # (total_actions, N)
        scores = scores.masked_fill(~expanded_mask, torch.finfo(scores.dtype).min)
        attn_weights = torch.softmax(scores, dim=-1).unsqueeze(1) # (total_actions, 1, N)

        queried_entity_context = torch.bmm(attn_weights, V).squeeze(1) # (total_actions, h)
        action_context = self.action_entity_mix(torch.cat([action_emb, queried_entity_context], dim=-1)) # (total_actions, h)

        # Policy head: [state, action_context, expanded_state * action_context, action_emb * queried_entity_context]
        policy_input = torch.cat([
            expanded_state,
            action_context,
            expanded_state * action_context,
            action_emb * queried_entity_context,
        ], dim=-1) # (total_actions, 4*h)

        logits = self.policy(policy_input).squeeze(-1) # (total_actions,)
        return logits, self.value(state)
