from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn

from squashvision.model_assets import (
    APPLICATION_COMPATIBILITY_VERSION,
    BALL_ASSET,
    ResolvedAsset,
)
from squashvision.models import ModelAssetState
from squashvision.settings import Settings

_DOCUMENTED_PREFIXES = ("module.", "model.", "_orig_mod.")
TRUSTED_BALL_REVISION = "a3760773233a0988c9605259743fbdd87c59d3a3"
TRUSTED_BALL_SHA256 = "00d707b9db7a49561c411e4765956e79bcd7c7e20c7a0a535073440b3e972342"
TRUSTED_BALL_BYTE_SIZE = 46_585_585
_MODEL_ROOTS = {
    "down_block_1",
    "down_block_2",
    "down_block_3",
    "bottleneck",
    "up_block_1",
    "up_block_2",
    "up_block_3",
    "predictor",
}


class CheckpointFormatError(ValueError):
    """A restricted checkpoint does not exactly describe TrackNetV3."""


class Conv2DBlock(nn.Module):
    def __init__(self, in_dim: int, out_dim: int) -> None:
        super().__init__()
        self.conv = nn.Conv2d(in_dim, out_dim, kernel_size=3, padding="same", bias=False)
        self.bn = nn.BatchNorm2d(out_dim)
        self.relu = nn.ReLU()

    def forward(self, values: Tensor) -> Tensor:
        return self.relu(self.bn(self.conv(values)))


class Double2DConv(nn.Module):
    def __init__(self, in_dim: int, out_dim: int) -> None:
        super().__init__()
        self.conv_1 = Conv2DBlock(in_dim, out_dim)
        self.conv_2 = Conv2DBlock(out_dim, out_dim)

    def forward(self, values: Tensor) -> Tensor:
        return self.conv_2(self.conv_1(values))


class Triple2DConv(nn.Module):
    def __init__(self, in_dim: int, out_dim: int) -> None:
        super().__init__()
        self.conv_1 = Conv2DBlock(in_dim, out_dim)
        self.conv_2 = Conv2DBlock(out_dim, out_dim)
        self.conv_3 = Conv2DBlock(out_dim, out_dim)

    def forward(self, values: Tensor) -> Tensor:
        return self.conv_3(self.conv_2(self.conv_1(values)))


def normalize_checkpoint_keys(state_dict: Mapping[str, Tensor]) -> dict[str, Tensor]:
    normalized: dict[str, Tensor] = {}
    for raw_key, value in state_dict.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise CheckpointFormatError("checkpoint state dict keys must be nonempty strings")
        key = raw_key
        stripped = True
        while stripped:
            stripped = False
            for prefix in _DOCUMENTED_PREFIXES:
                if key.startswith(prefix):
                    key = key[len(prefix) :]
                    stripped = True
                    break
        root = key.split(".", 1)[0]
        if root not in _MODEL_ROOTS:
            raise CheckpointFormatError(f"unexpected prefix or key in checkpoint: {raw_key}")
        if key in normalized:
            raise CheckpointFormatError(f"checkpoint key normalization collision: {key}")
        normalized[key] = value
    return normalized


def _tensor_state_dict(checkpoint: object) -> dict[str, Tensor]:
    candidate = checkpoint
    if isinstance(checkpoint, Mapping):
        envelope_keys = set(checkpoint)
        if envelope_keys == {"state_dict"}:
            candidate = checkpoint["state_dict"]
        elif envelope_keys == {"meta", "state_dict", "message_hub"}:
            candidate = checkpoint["state_dict"]
        elif "state_dict" in envelope_keys:
            raise CheckpointFormatError("checkpoint must contain a tensor state dict only")
    if not isinstance(candidate, Mapping) or not candidate:
        raise CheckpointFormatError("checkpoint must contain a nonempty tensor state dict only")
    if any(
        not isinstance(key, str) or not isinstance(value, Tensor)
        for key, value in candidate.items()
    ):
        raise CheckpointFormatError("checkpoint must contain a tensor state dict only")
    return normalize_checkpoint_keys(candidate)


class _HistoryBufferEnvelope:
    @staticmethod
    def min(*_args: object) -> None:
        return None

    @staticmethod
    def max(*_args: object) -> None:
        return None

    @staticmethod
    def mean(*_args: object) -> None:
        return None

    @staticmethod
    def current(*_args: object) -> None:
        return None


def _safe_history_getattr(target: object, name: str) -> object:
    if target is not _HistoryBufferEnvelope:
        raise ValueError("restricted checkpoint getattr target is not HistoryBuffer")
    methods = {
        "min": _HistoryBufferEnvelope.min,
        "max": _HistoryBufferEnvelope.max,
        "mean": _HistoryBufferEnvelope.mean,
        "current": _HistoryBufferEnvelope.current,
    }
    if name not in methods:
        raise ValueError(f"restricted checkpoint requested unknown HistoryBuffer method: {name}")
    return methods[name]


def _restricted_load(path: Path, device: torch.device) -> object:
    safe_globals: list[object] = [
        (
            _HistoryBufferEnvelope,
            "mmengine.logging.history_buffer.HistoryBuffer",
        ),
        (
            np._core.multiarray._reconstruct,
            "numpy.core.multiarray._reconstruct",
        ),
        np.ndarray,
        np.dtype,
        np.dtypes.Float64DType,
        np.dtypes.Int64DType,
        (
            np._core.multiarray.scalar,
            "numpy.core.multiarray.scalar",
        ),
        (_safe_history_getattr, "builtins.getattr"),
    ]
    existing_safe_globals = (
        torch.serialization.get_safe_globals()
    )
    torch.serialization.clear_safe_globals()
    try:
        with torch.serialization.safe_globals(safe_globals):
            return torch.load(
                path,
                map_location=device,
                weights_only=True,
            )
    finally:
        torch.serialization.clear_safe_globals()
        torch.serialization.add_safe_globals(
            existing_safe_globals
        )


def _validated_asset_path(
    asset: ResolvedAsset, storage_root: Path | None = None
) -> Path:
    if not isinstance(asset, ResolvedAsset):
        raise TypeError("TrackNetV3.load requires a ResolvedAsset")
    if asset.state is not ModelAssetState.READY:
        raise ValueError("TrackNetV3 requires a READY ball model asset")
    if asset.compatibility_version != APPLICATION_COMPATIBILITY_VERSION:
        raise ValueError("ball model asset is incompatible with this application")
    if (
        asset.name != BALL_ASSET.name
        or asset.source != BALL_ASSET.source
        or asset.url is not None
        or asset.repository != BALL_ASSET.repo_id
        or asset.filename != BALL_ASSET.filename
        or asset.requested_revision != BALL_ASSET.revision
        or not asset.resolved_revision
        or asset.error_code is not None
        or asset.downloaded_at is None
        or not asset.required
    ):
        raise ValueError("resolved model asset does not match the approved ball specification")
    if (
        asset.resolved_revision != TRUSTED_BALL_REVISION
        or asset.sha256 != TRUSTED_BALL_SHA256
        or asset.byte_size != TRUSTED_BALL_BYTE_SIZE
    ):
        raise ValueError("resolved ball asset does not match the trusted checkpoint identity")
    if (
        len(asset.resolved_revision) != 40
        or any(
            character not in "0123456789abcdef"
            for character in asset.resolved_revision
        )
    ):
        raise ValueError("resolved ball asset requires an immutable revision")
    if (
        asset.local_path is None
        or asset.sha256 is None
        or len(asset.sha256) != 64
        or any(character not in "0123456789abcdef" for character in asset.sha256)
        or asset.byte_size is None
        or asset.byte_size <= 0
    ):
        raise ValueError("READY ball asset is missing integrity provenance")
    relative = Path(asset.local_path)
    expected_relative = Path("models") / f"{asset.sha256}.pth"
    if relative.is_absolute():
        raise ValueError("resolved ball asset must remain inside managed storage")
    if relative != expected_relative:
        raise ValueError("resolved ball asset path does not match its digest")
    storage_root = Path(
        Settings().storage_root if storage_root is None else storage_root
    ).expanduser().resolve()
    path = (storage_root / relative).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError as error:
        raise ValueError("resolved ball asset escapes managed storage") from error
    if not path.is_file():
        raise FileNotFoundError(f"resolved ball asset does not exist: {path}")
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as model_file:
        while chunk := model_file.read(64 * 1024):
            byte_size += len(chunk)
            digest.update(chunk)
    if byte_size != asset.byte_size or digest.hexdigest() != asset.sha256:
        raise ValueError("resolved ball asset digest or size no longer matches")
    return path


class TrackNetV3(nn.Module):
    """Inference-only TrackNetV3 U-Net ported from RacketVision."""

    def __init__(
        self,
        in_dim: int = 15,
        out_dim: int = 4,
        *,
        last_only: bool = True,
        base_width: int = 64,
    ) -> None:
        super().__init__()
        if in_dim <= 0 or out_dim <= 0 or base_width <= 0:
            raise ValueError("TrackNetV3 dimensions must be positive")
        self.last_only = last_only
        self.down_block_1 = Double2DConv(in_dim, base_width)
        self.down_block_2 = Double2DConv(base_width, base_width * 2)
        self.down_block_3 = Triple2DConv(base_width * 2, base_width * 4)
        self.bottleneck = Triple2DConv(base_width * 4, base_width * 8)
        self.up_block_1 = Triple2DConv(base_width * 12, base_width * 4)
        self.up_block_2 = Double2DConv(base_width * 6, base_width * 2)
        self.up_block_3 = Double2DConv(base_width * 3, base_width)
        self.predictor = nn.Conv2d(base_width, out_dim, (1, 1))
        self.sigmoid = nn.Sigmoid()

    def forward(self, values: Tensor) -> Tensor:
        first = self.down_block_1(values)
        second = self.down_block_2(nn.functional.max_pool2d(first, 2, 2))
        third = self.down_block_3(nn.functional.max_pool2d(second, 2, 2))
        values = self.bottleneck(nn.functional.max_pool2d(third, 2, 2))
        values = torch.cat((nn.functional.interpolate(values, scale_factor=2), third), dim=1)
        values = self.up_block_1(values)
        values = torch.cat((nn.functional.interpolate(values, scale_factor=2), second), dim=1)
        values = self.up_block_2(values)
        values = torch.cat((nn.functional.interpolate(values, scale_factor=2), first), dim=1)
        values = self.sigmoid(self.predictor(self.up_block_3(values)))
        return values[:, -1:, :, :] if self.last_only else values

    @classmethod
    def load(
        cls,
        asset: ResolvedAsset,
        device: torch.device,
        *,
        storage_root: Path | None = None,
    ) -> TrackNetV3:
        path = (
            _validated_asset_path(asset)
            if storage_root is None
            else _validated_asset_path(asset, storage_root)
        )
        checkpoint: Any = _restricted_load(path, device)
        state_dict = _tensor_state_dict(checkpoint)
        model = cls(in_dim=15, out_dim=4, last_only=True, base_width=64)
        expected = model.state_dict()
        missing = sorted(set(expected).difference(state_dict))
        unexpected = sorted(set(state_dict).difference(expected))
        mismatched = sorted(
            key
            for key in set(expected).intersection(state_dict)
            if expected[key].shape != state_dict[key].shape
        )
        if missing or unexpected or mismatched:
            raise CheckpointFormatError(
                "strict TrackNetV3 checkpoint mismatch: "
                f"missing={missing}, unexpected={unexpected}, shape_mismatched={mismatched}"
            )
        model.load_state_dict(state_dict, strict=True)
        model.to(device)
        model.eval()
        return model


__all__ = [
    "CheckpointFormatError",
    "Conv2DBlock",
    "Double2DConv",
    "TrackNetV3",
    "Triple2DConv",
    "normalize_checkpoint_keys",
]
