"""Compact trainable heads over cached frozen features.

Import this module only in an explicitly authorized model-execution stage.
No foundation-model weights are downloaded or trained here.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class ResidueMLP(nn.Module):
    def __init__(self, width: int = 640, dropout: float = 0.1):
        super().__init__()
        self.network = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, 256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, 128),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(128, 1),
        )

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        return self.network(embeddings).squeeze(-1)


class ResidueLinearProbe(nn.Module):
    def __init__(self, width: int = 640):
        super().__init__()
        self.output = nn.Linear(width, 1)

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        return self.output(embeddings).squeeze(-1)


class SiteRanker(nn.Module):
    def __init__(
        self, input_width: int, *, nonlinear: bool = False, dropout: float = 0.1, zero_output: bool = False
    ):
        super().__init__()
        self.network = (
            nn.Sequential(
                nn.Linear(input_width, 64),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(64, 32),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(32, 1),
            )
            if nonlinear
            else nn.Sequential(nn.Linear(input_width, 1))
        )
        if zero_output:
            nn.init.zeros_(self.network[-1].weight)
            nn.init.zeros_(self.network[-1].bias)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


class EnsembleRanker(nn.Module):
    """Freeze both S0 weights AND dropout behavior; exact fallback without frames."""

    def __init__(
        self, static: SiteRanker, ensemble_width: int, *, nonlinear: bool = False, dropout: float = 0.1
    ):
        super().__init__()
        self.static = static.requires_grad_(False).eval()
        self.correction = SiteRanker(ensemble_width, nonlinear=nonlinear, dropout=dropout, zero_output=True)

    def train(self, mode: bool = True):
        super().train(mode)
        self.static.eval()
        return self

    def forward(
        self,
        static_features: torch.Tensor,
        ensemble_features: torch.Tensor,
        ensemble_available: bool | torch.Tensor,
    ) -> torch.Tensor:
        with torch.no_grad():
            base = self.static(static_features)
        delta = self.correction(ensemble_features)
        mask = torch.as_tensor(ensemble_available, dtype=torch.bool, device=base.device)
        return base + torch.where(mask, delta, torch.zeros_like(delta))


def residue_loss(
    logits: torch.Tensor, labels: torch.Tensor, mask: torch.Tensor, positive_weight: float = 1.0
) -> torch.Tensor | None:
    if logits.shape != labels.shape or mask.shape != labels.shape or mask.dtype != torch.bool:
        raise ValueError("Residue logits, labels and boolean mask must have identical shape")
    if not bool(mask.any()):
        return None
    selected = labels[mask]
    if not bool(((selected == 0) | (selected == 1)).all()):
        raise ValueError("Residue supervision must be binary")
    if not positive_weight > 0:
        raise ValueError("Positive class weight must be positive")
    weight = torch.as_tensor(positive_weight, dtype=logits.dtype, device=logits.device)
    return F.binary_cross_entropy_with_logits(logits[mask], selected.to(logits.dtype), pos_weight=weight)


def pairwise_loss(scores: torch.Tensor, pairs: torch.Tensor) -> torch.Tensor | None:
    if pairs.ndim != 2 or pairs.shape[1] != 2:
        raise ValueError("Ranking pairs must have shape [P,2]")
    if len(pairs) == 0:
        return None
    if (
        scores.ndim != 1
        or pairs.dtype != torch.long
        or int(pairs.min()) < 0
        or int(pairs.max()) >= len(scores)
    ):
        raise ValueError("Ranking pairs must index this target's score vector")
    return F.softplus(-(scores[pairs[:, 0]] - scores[pairs[:, 1]])).mean()


def parameter_counts(model: nn.Module) -> dict[str, int]:
    return {
        "total": sum(p.numel() for p in model.parameters()),
        "trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
    }
