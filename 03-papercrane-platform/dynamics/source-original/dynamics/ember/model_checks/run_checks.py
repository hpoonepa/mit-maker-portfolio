"""DEFERRED checks that execute small models. Not part of local contract tests.

Run only after model-execution authorization:
    python -m dynamics.ember.model_checks.run_checks --execute-model

No foundation checkpoints, network calls or GPUs are used by these CPU checks.
They are intentionally unrun during the 2026-09-28 no-compute build.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from dynamics.ember.execution import ExecutionPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-model", action="store_true")
    args = parser.parse_args()
    policy = ExecutionPolicy(args.execute_model)
    policy.require_model_execution("Deferred CPU model checks")
    import numpy as np
    import torch
    from dynamics.ember.models import EnsembleRanker, ResidueMLP, SiteRanker, pairwise_loss, residue_loss
    from dynamics.ember.train import TrainingConfig, TrainingExample, fit, load_checkpoint

    torch.set_num_threads(1)
    torch.manual_seed(1729)
    passed = []

    # Masks control both loss and gradient: padding cannot alter supervision.
    logits = torch.tensor([0.0, 0.0, 100.0], requires_grad=True)
    labels = torch.tensor([1.0, 0.0, 0.0])
    mask = torch.tensor([True, True, False])
    loss = residue_loss(logits, labels, mask)
    loss.backward()
    assert logits.grad[0] < 0 and logits.grad[1] > 0 and logits.grad[2] == 0
    scores = torch.tensor([0.0, 0.0], requires_grad=True)
    pairwise_loss(scores, torch.tensor([[0, 1]])).backward()
    assert scores.grad[0] < 0 < scores.grad[1]
    passed.append("loss masks and ranking gradient direction")

    static = SiteRanker(4, nonlinear=True)
    ensemble = EnsembleRanker(static, 6, nonlinear=True).train()
    x, z = torch.randn(5, 4), torch.randn(5, 6)
    assert not ensemble.static.training
    assert not any(p.requires_grad for p in ensemble.static.parameters())
    baseline = static(x).detach()
    assert torch.equal(ensemble(x, z, True), baseline)
    assert torch.equal(ensemble(x, z, False), baseline)
    with torch.no_grad():
        ensemble.correction.network[-1].bias.fill_(5.0)
    assert torch.equal(ensemble(x, z, False), baseline)
    ensemble.eval()
    order = torch.tensor([3, 1, 4, 0, 2])
    assert torch.allclose(ensemble(x[order], z[order], True), ensemble(x, z, True)[order])
    passed.append("frozen static dropout, zero correction, exact fallback, site permutation")

    # Tiny artificial overfit sanity check; no biological accuracy claim.
    model = ResidueMLP(width=2, dropout=0.0)
    features = torch.tensor([[-2.0, 1.0], [-1.0, 1.0], [1.0, -1.0], [2.0, -1.0]])
    labels = torch.tensor([0.0, 0.0, 1.0, 1.0])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    for _ in range(80):
        optimizer.zero_grad()
        loss = residue_loss(model(features), labels, torch.ones(4, dtype=torch.bool))
        loss.backward()
        optimizer.step()
    model.eval()
    assert torch.equal((model(features) > 0).float(), labels)
    passed.append("tiny synthetic R0 overfit")

    # Resume at an optimizer boundary in mid-epoch, then compare exact CPU weights.
    examples = [
        TrainingExample(
            f"train{i}",
            f"g{i}",
            "train",
            np.array([[-1.0, 1.0], [1.0, -1.0]], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
            np.ones(2, dtype=bool),
        )
        for i in range(4)
    ]
    dev = [
        TrainingExample(
            "development", "dev", "development", examples[0].features, examples[0].labels, examples[0].mask
        )
    ]
    config = TrainingConfig(
        kind="residue_mlp", effective_batch_proteins=2, maximum_epochs=3, patience=5, maximum_seconds=100.0
    )
    with tempfile.TemporaryDirectory() as folder:
        uninterrupted, interrupted = Path(folder) / "uninterrupted", Path(folder) / "interrupted"
        common = dict(config=config, policy=policy, split_sha256="a" * 64, code_sha256="b" * 64)
        fit(examples, dev, output_dir=uninterrupted, **common)
        with patch("dynamics.ember.train.time.monotonic", side_effect=[0.0, 0.0, 101.0, 101.0]):
            stopped = fit(examples, dev, output_dir=interrupted, **common)
        assert stopped["stop_reason"] == "time_limit"
        assert stopped["progress"]["cursor"] == 2
        fit(examples, dev, output_dir=interrupted, resume=interrupted / "latest.pt", **common)
        a = load_checkpoint(uninterrupted / "latest.pt", policy=policy)
        b = load_checkpoint(interrupted / "latest.pt", policy=policy)
        assert a["progress"] == b["progress"]
        assert all(torch.equal(a["model"][name], b["model"][name]) for name in a["model"])
    passed.append("interrupted vs uninterrupted optimizer/RNG/sampler resume parity")
    print("Passed deferred model checks:")
    for name in passed:
        print("- " + name)


if __name__ == "__main__":
    main()
