"""Bounded cached-feature training with resumable optimizer-boundary checkpoints.

This implementation awaits model execution checks. Every public training entry
requires an explicit ExecutionPolicy; infrastructure provisioning is a separate
step. Torch is imported only after the execution gate.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .checkpoint_store import checkpoint_reader, publish_checkpoint
from .execution import ExecutionPolicy
from .io import atomic_write_json, content_hash


@dataclass(frozen=True)
class TrainingConfig:
    kind: str = "residue_mlp"
    seed: int = 1729
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    dropout: float = 0.1
    gradient_clip: float = 1.0
    effective_batch_proteins: int = 8
    maximum_epochs: int = 50
    patience: int = 5
    maximum_seconds: float = 3600.0
    positive_weight: float = 1.0
    pair_cap: int = 256
    positive_overlap: float = 0.25
    nonmatch_overlap: float = 0.1
    device: str = "cpu"
    ensemble_variant: str = "all"

    def __post_init__(self) -> None:
        if self.kind not in {
            "residue_mlp",
            "residue_linear",
            "site_linear",
            "site_mlp",
            "ensemble_linear",
            "ensemble_mlp",
        }:
            raise ValueError("Unsupported model kind")
        if self.ensemble_variant not in {"all", "no_support_counts"} or (
            not self.kind.startswith("ensemble") and self.ensemble_variant != "all"
        ):
            raise ValueError("Ensemble ablation applies only to ensemble models")
        for name in ("learning_rate", "gradient_clip", "maximum_seconds", "positive_weight"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(self.weight_decay) or self.weight_decay < 0 or not 0 <= self.dropout < 1:
            raise ValueError("Invalid regularization settings")
        for name in ("effective_batch_proteins", "maximum_epochs", "patience", "pair_cap"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 <= self.nonmatch_overlap < self.positive_overlap <= 1:
            raise ValueError("Invalid ranking-label thresholds")
        if self.device not in {"cpu", "cuda", "mps"} or type(self.seed) is not int or self.seed < 0:
            raise ValueError("Invalid device or seed")


@dataclass(frozen=True)
class TrainingExample:
    target_id: str
    group_id: str
    partition: str
    features: np.ndarray
    labels: np.ndarray
    mask: np.ndarray | None = None
    ensemble: np.ndarray | None = None
    ensemble_available: bool = False
    site_ids: tuple[str, ...] = ()
    site_residues: tuple[tuple[int, ...], ...] = ()
    reference_residues: tuple[tuple[int, ...], ...] = ()

    def validate(self, config: TrainingConfig) -> None:
        if self.partition not in {"train", "development"}:
            raise ValueError("Training/selection loader refuses test and external records")
        if not self.target_id or not self.group_id:
            raise ValueError("Training example lacks identity")
        if (
            self.features.ndim != 2
            or self.features.dtype != np.float32
            or not np.isfinite(self.features).all()
        ):
            raise ValueError("Training features must be normalized finite float32 matrices")
        if self.labels.shape != (len(self.features),) or not np.isfinite(self.labels).all():
            raise ValueError("Training label shape/nonfinite error")
        if config.kind.startswith("residue"):
            if self.mask is None or self.mask.shape != self.labels.shape or self.mask.dtype != bool:
                raise ValueError("Residue labels require a boolean mask")
            if not np.isin(self.labels, [0, 1]).all():
                raise ValueError("Residue labels must be binary")
        else:
            if ((self.labels < 0) | (self.labels > 1)).any():
                raise ValueError("Site labels must be overlap fractions")
            if (
                len(self.site_ids) != len(self.features)
                or len(set(self.site_ids)) != len(self.site_ids)
                or len(self.site_residues) != len(self.features)
            ):
                raise ValueError("Site identities/residue sets must match feature rows")
            if any(not residues for residues in self.site_residues + self.reference_residues):
                raise ValueError("Site residue sets must be nonempty")
            if config.kind.startswith("ensemble"):
                if (
                    self.ensemble is None
                    or self.ensemble.ndim != 2
                    or self.ensemble.dtype != np.float32
                    or len(self.ensemble) != len(self.features)
                    or not np.isfinite(self.ensemble).all()
                ):
                    raise ValueError("Ensemble feature matrix missing or invalid")


def training_signature(examples: list[TrainingExample]) -> str:
    """Bind checkpoints to identities, partitions, labels AND actual feature bytes."""
    import hashlib

    rows = []
    for example in sorted(examples, key=lambda x: x.target_id):
        row = {
            name: getattr(example, name)
            for name in (
                "target_id",
                "group_id",
                "partition",
                "ensemble_available",
                "site_ids",
                "site_residues",
                "reference_residues",
            )
        }
        for name in ("features", "labels", "mask", "ensemble"):
            array = getattr(example, name)
            row[name] = (
                None
                if array is None
                else {
                    "shape": list(array.shape),
                    "dtype": str(array.dtype),
                    "sha256": hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest(),
                }
            )
        rows.append(row)
    return content_hash(rows)


def _new_model(config: TrainingConfig, width: int, ensemble_width: int | None, static_model=None):
    from .models import EnsembleRanker, ResidueLinearProbe, ResidueMLP, SiteRanker

    if config.kind == "residue_mlp":
        return ResidueMLP(width, config.dropout)
    if config.kind == "residue_linear":
        return ResidueLinearProbe(width)
    if config.kind.startswith("site"):
        return SiteRanker(width, nonlinear=config.kind.endswith("mlp"), dropout=config.dropout)
    if static_model is None or ensemble_width is None:
        raise ValueError("E0 requires a frozen, trained S0 model and ensemble features")
    return EnsembleRanker(
        static_model, ensemble_width, nonlinear=config.kind.endswith("mlp"), dropout=config.dropout
    )


def _save_checkpoint(path: Path, payload: dict) -> str:
    import torch

    return publish_checkpoint(path, lambda handle: torch.save(payload, handle))


def load_checkpoint(path: str | Path, *, policy: ExecutionPolicy) -> dict:
    policy.require_model_execution("Model checkpoint loading")
    import torch

    # Payload uses tensors and built-in containers only. Never unpickle arbitrary
    # NumPy state/classes by setting weights_only=False.
    with checkpoint_reader(path) as (handle, _digest):
        return torch.load(handle, map_location="cpu", weights_only=True)


def _rng_state(device: str) -> dict:
    import torch

    return {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if device == "cuda" else [],
        "torch_mps": torch.mps.get_rng_state() if device == "mps" else None,
    }


def _restore_rng(state: dict) -> None:
    import torch

    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"])
    if state["torch_cuda"]:
        if not torch.cuda.is_available():
            raise ValueError("CUDA RNG checkpoint requires CUDA for exact resume")
        torch.cuda.set_rng_state_all(state["torch_cuda"])
    if state["torch_mps"] is not None:
        if not torch.backends.mps.is_available():
            raise ValueError("MPS RNG checkpoint requires MPS for exact resume")
        torch.mps.set_rng_state(state["torch_mps"])


def _scores(model, example: TrainingExample, config: TrainingConfig):
    import torch

    features = torch.as_tensor(example.features, device=config.device)
    if config.kind.startswith("ensemble"):
        from .features import ensemble_ablation

        values = (
            ensemble_ablation(example.ensemble, config.ensemble_variant)
            if config.ensemble_variant != "all"
            else example.ensemble
        )
        ensemble = torch.as_tensor(values, device=config.device)
        return model(features, ensemble, example.ensemble_available)
    return model(features)


def _development_metric(model, examples: list[TrainingExample], config: TrainingConfig) -> tuple[float, int]:
    import torch

    from .candidates import ranked_unique
    from .evaluate import average_precision, maximum_matching
    from .schema import RankedSite

    values = []
    undefined = 0
    model.eval()
    with torch.inference_mode():
        for example in examples:
            scores = _scores(model, example, config).float().cpu().tolist()
            if config.kind.startswith("residue"):
                score = average_precision(example.labels.astype(int).tolist(), scores, example.mask.tolist())
            else:
                sites = [
                    RankedSite(site_id, residues, value, "apo")
                    for site_id, residues, value in zip(example.site_ids, example.site_residues, scores)
                ]
                top = ranked_unique(sites, top_k=3, dedup_jaccard=0.5)
                n = len(example.reference_residues)
                score = (
                    len(maximum_matching([s.residues for s in top], example.reference_residues, 0.25)) / n
                    if n
                    else None
                )
            if score is None:
                undefined += 1
            else:
                values.append(score)
    if not values:
        raise ValueError("No defined development metrics; cannot select a model")
    return sum(values) / len(values), undefined


def fit(
    train_examples: list[TrainingExample],
    development_examples: list[TrainingExample],
    *,
    config: TrainingConfig,
    output_dir: str | Path,
    policy: ExecutionPolicy,
    split_sha256: str,
    code_sha256: str,
    static_model=None,
    static_checkpoint_sha256: str | None = None,
    release_binding_sha256: str | None = None,
    resume: str | Path | None = None,
) -> dict:
    """Fit small heads only. A timed stop saves progress but grants no cloud permission.

    Checkpoints occur only after whole accumulation batches. Replaying an epoch
    uses a separate deterministic sampler RNG, so dropout RNG is not consumed.
    Exact replay across different hardware/library versions is not promised.
    """
    policy.require_model_execution("Ember cached-feature training")
    from .schema import require_hash

    require_hash(split_sha256, "split_sha256")
    require_hash(code_sha256, "code_sha256")
    if release_binding_sha256 is not None:
        require_hash(release_binding_sha256, "release_binding_sha256")
    if config.kind.startswith("ensemble"):
        require_hash(static_checkpoint_sha256, "static_checkpoint_sha256")
    all_examples = train_examples + development_examples
    if not train_examples or not development_examples:
        raise ValueError("Nonempty train and development cohorts required")
    if any(x.partition != "train" for x in train_examples) or any(
        x.partition != "development" for x in development_examples
    ):
        raise ValueError("Wrong partitions supplied to train/development")
    if len({x.target_id for x in all_examples}) != len(all_examples):
        raise ValueError("Duplicate target across training/selection inputs")
    if {x.group_id for x in train_examples} & {x.group_id for x in development_examples}:
        raise ValueError("Relatedness groups cross training/development")
    for example in all_examples:
        example.validate(config)
    widths = {x.features.shape[1] for x in all_examples}
    if len(widths) != 1:
        raise ValueError("Feature widths vary across examples")
    width = widths.pop()
    ensemble_width = None
    if config.kind.startswith("ensemble"):
        widths = {x.ensemble.shape[1] for x in all_examples}
        if len(widths) != 1:
            raise ValueError("Ensemble feature widths vary")
        ensemble_width = widths.pop()
    import torch

    from .models import pairwise_loss, parameter_counts, residue_loss
    from .supervision import ranking_pairs

    train_examples = sorted(train_examples, key=lambda x: x.target_id)
    development_examples = sorted(development_examples, key=lambda x: x.target_id)
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    # CPU path is used for future resume-parity tests. Unsupported deterministic
    # GPU kernels fail visibly rather than silently claiming reproducibility.
    torch.use_deterministic_algorithms(True)
    model = _new_model(config, width, ensemble_width, static_model).to(config.device)
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer_cls = torch.optim.Adam if config.kind.endswith("linear") else torch.optim.AdamW
    optimizer = optimizer_cls(parameters, lr=config.learning_rate, weight_decay=config.weight_decay)
    signature = {
        "data": training_signature(all_examples),
        "config": content_hash(config),
        "split_sha256": split_sha256,
        "code_sha256": code_sha256,
        "static_checkpoint_sha256": static_checkpoint_sha256,
        "release_binding_sha256": release_binding_sha256,
        "torch_version": str(torch.__version__),
        "numpy_version": str(np.__version__),
    }
    output = Path(output_dir)
    if resume is not None and Path(resume).absolute().parent.resolve() != output.resolve():
        raise ValueError("Resume inside the copied whole run directory so prior best checkpoints survive")
    if output.exists() and any(output.iterdir()) and resume is None:
        raise ValueError("Training output must be empty unless explicitly resuming")
    output.mkdir(parents=True, exist_ok=True)
    progress = {
        "epoch": 0,
        "cursor": 0,
        "optimizer_steps": 0,
        "best_metric": None,
        "bad_epochs": 0,
        "history": [],
        "epoch_loss_sum": 0.0,
        "epoch_loss_count": 0,
    }
    if resume is not None:
        checkpoint = load_checkpoint(resume, policy=policy)
        if checkpoint["signature"] != signature:
            raise ValueError("Resume config/data/code/environment mismatch")
        model.load_state_dict(checkpoint["model"], strict=True)
        optimizer.load_state_dict(checkpoint["optimizer"])
        progress = checkpoint["progress"]
        _restore_rng(checkpoint["rng"])
    started = time.monotonic()

    def save(name):
        return _save_checkpoint(
            output / name,
            {
                "schema_version": "1",
                "signature": signature,
                "config": asdict(config),
                "width": width,
                "ensemble_width": ensemble_width,
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": None,
                "amp_scaler": None,
                "rng": _rng_state(config.device),
                "progress": progress,
                "parameter_counts": parameter_counts(model),
            },
        )

    stop_reason = "maximum_epochs"
    while progress["epoch"] < config.maximum_epochs:
        if progress["bad_epochs"] >= config.patience:
            stop_reason = "development_early_stop"
            break
        epoch = progress["epoch"]
        order = list(range(len(train_examples)))
        random.Random(config.seed + epoch).shuffle(order)
        model.train()
        while progress["cursor"] < len(order):
            if time.monotonic() - started >= config.maximum_seconds:
                stop_reason = "time_limit"
                break
            batch = order[progress["cursor"] : progress["cursor"] + config.effective_batch_proteins]
            optimizer.zero_grad(set_to_none=True)
            losses = []
            for index in batch:
                example = train_examples[index]
                scores = _scores(model, example, config)
                if config.kind.startswith("residue"):
                    loss = residue_loss(
                        scores,
                        torch.as_tensor(example.labels, device=config.device),
                        torch.as_tensor(example.mask, device=config.device),
                        config.positive_weight,
                    )
                else:
                    pairs = ranking_pairs(
                        example.labels,
                        positive_min=config.positive_overlap,
                        nonmatch_max_exclusive=config.nonmatch_overlap,
                        maximum_pairs=config.pair_cap,
                        seed=config.seed + epoch,
                    )
                    loss = pairwise_loss(
                        scores, torch.as_tensor(pairs, dtype=torch.long, device=config.device)
                    )
                if loss is not None:
                    if not bool(torch.isfinite(loss)):
                        raise ValueError(f"Nonfinite loss for {example.target_id}")
                    losses.append(loss)
            if losses:
                loss = torch.stack(losses).mean()  # equal weight per contributing protein
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, config.gradient_clip, error_if_nonfinite=True)
                optimizer.step()
                progress["optimizer_steps"] += 1
                progress["epoch_loss_sum"] += sum(float(x.detach().cpu()) for x in losses)
                progress["epoch_loss_count"] += len(losses)
            progress["cursor"] += len(batch)
            save("latest.pt")
        if stop_reason == "time_limit":
            break
        if progress["epoch_loss_count"] == 0:
            raise ValueError("No supervised proteins contributed this epoch; check labels/candidate coverage")
        metric, undefined = _development_metric(model, development_examples, config)
        improved = progress["best_metric"] is None or metric > progress["best_metric"]
        progress["history"].append(
            {
                "epoch": epoch,
                "development_metric": metric,
                "development_undefined_targets": undefined,
                "training_mean_loss": progress["epoch_loss_sum"] / progress["epoch_loss_count"],
            }
        )
        progress["epoch"] += 1
        progress["cursor"] = 0
        progress["epoch_loss_sum"] = 0.0
        progress["epoch_loss_count"] = 0
        progress["bad_epochs"] = 0 if improved else progress["bad_epochs"] + 1
        if improved:
            progress["best_metric"] = metric
            save("best-development.pt")
        save("latest.pt")
    digest = save("latest.pt")
    report = {
        "stop_reason": stop_reason,
        "signature": signature,
        "progress": progress,
        "parameter_counts": parameter_counts(model),
        "latest_sha256": digest,
        "session_runtime_seconds": time.monotonic() - started,
        "best_checkpoint_available": (output / "best-development.pt").exists(),
        "test_evaluation_performed": False,
        "mixed_precision": False,
        "note": "Provider billing and resource shutdown are not managed by this trainer.",
    }
    atomic_write_json(output / "training-report.json", report)
    return report
