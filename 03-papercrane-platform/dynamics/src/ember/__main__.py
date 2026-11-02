"""Safe-by-default CLI. Heavy dependencies are loaded only for their subcommand."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .execution import ComputeDisabled, ExecutionPolicy
from .io import atomic_write_json, read_json, read_jsonl


def _emit(result: dict, output: str | None) -> None:
    if output:
        atomic_write_json(output, result)
        print(f"Wrote {output}")
    else:
        print(json.dumps(result, indent=2, allow_nan=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Ember Pocket: local preparation by default; no automatic cloud jobs."
    )
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("plan", "research-inventory"):
        command = sub.add_parser(name)
        command.add_argument("--output")
    command = sub.add_parser("preflight")
    command.add_argument("plan_file")
    command.add_argument("--output")
    command = sub.add_parser("audit-targets")
    command.add_argument("targets")
    command.add_argument("--verify-files", action="store_true")
    command.add_argument("--output")
    command = sub.add_parser("audit-cryptobench")
    command.add_argument("dataset_json")
    command.add_argument("--output")
    command = sub.add_parser("crossfit-plan")
    command.add_argument("targets")
    command.add_argument("--folds", type=int, default=3)
    command.add_argument("--selection-fraction", type=float, default=0.2)
    command.add_argument("--seed", type=int, default=1729)
    command.add_argument("--output")
    command = sub.add_parser("sampling-plan")
    command.add_argument("--sequence", required=True)
    command.add_argument("--output-dir", required=True)
    command.add_argument("--samples", type=int, default=16)
    command.add_argument("--seed", type=int, default=1729)
    command.add_argument("--output")
    command = sub.add_parser("check-prepared")
    command.add_argument("directory")
    command.add_argument("--output")
    command = sub.add_parser("evaluate")
    command.add_argument("--targets", required=True)
    command.add_argument("--references", required=True)
    command.add_argument("--predictions", required=True)
    command.add_argument("--method-id", required=True)
    command.add_argument("--output")
    command = sub.add_parser("compare")
    command.add_argument("left")
    command.add_argument("right")
    command.add_argument("--resamples", type=int, default=10000)
    command.add_argument("--output")
    for name in ("train-residue", "train-sites"):
        command = sub.add_parser(name)
        command.add_argument("--targets", required=True)
        command.add_argument("--references", required=True)
        command.add_argument("--config", required=True)
        command.add_argument("--output-dir", required=True)
        command.add_argument("--method-id", required=True)
        command.add_argument(
            "--execute-model",
            action="store_true",
            help="Only after separate user authorization for model execution.",
        )
        command.add_argument("--resume")
        if name == "train-residue":
            command.add_argument("--embedding-keys", required=True)
            command.add_argument("--embedding-cache", required=True)
        else:
            command.add_argument("--bundle-index", required=True)
            command.add_argument("--base-release")
    command = sub.add_parser("predict")
    command.add_argument("--bundle", required=True)
    command.add_argument("--release", required=True)
    command.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    command.add_argument("--top-k", type=int, choices=(1, 3, 5), default=3)
    command.add_argument("--execute-model", action="store_true")
    command.add_argument("--output")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            from .plan import experiment_plan

            _emit(experiment_plan(), args.output)
        elif args.command == "research-inventory":
            from .plan import research_inventory

            _emit(research_inventory(), args.output)
        elif args.command == "preflight":
            from .plan import preflight

            report = preflight(read_json(args.plan_file))
            _emit(report, args.output)
            return 0 if report["ready_for_full_paid_experiment"] else 2
        elif args.command == "audit-targets":
            from .data import load_targets, manifest_summary

            _emit(manifest_summary(load_targets(args.targets, verify_files=args.verify_files)), args.output)
        elif args.command == "audit-cryptobench":
            from .data import inspect_cryptobench_schema

            _emit(inspect_cryptobench_schema(args.dataset_json), args.output)
        elif args.command == "crossfit-plan":
            from .data import load_targets
            from .splits import crossfit_plan

            _emit(
                crossfit_plan(
                    load_targets(args.targets),
                    folds=args.folds,
                    selection_fraction=args.selection_fraction,
                    seed=args.seed,
                ),
                args.output,
            )
        elif args.command == "sampling-plan":
            from .sampling import plan_bioemu

            _emit(
                asdict(
                    plan_bioemu(args.sequence, args.output_dir, requested_frames=args.samples, seed=args.seed)
                ),
                args.output,
            )
        elif args.command == "check-prepared":
            from .prepared import read_prepared

            bundle = read_prepared(args.directory)
            _emit(
                {
                    "target_id": bundle.target.target_id,
                    "sites": len(bundle.sites),
                    "static_shape": list(bundle.static.shape),
                    "ensemble_shape": list(bundle.ensemble.shape),
                    "valid_frames": len(bundle.valid_frame_ids),
                    "checksum_verified": True,
                },
                args.output,
            )
        elif args.command == "evaluate":
            from .data import load_references, load_targets
            from .evaluate import evaluate_method
            from .schema import Prediction, from_dict

            predictions = [from_dict(Prediction, row) for row in read_jsonl(args.predictions)]
            _emit(
                evaluate_method(
                    load_targets(args.targets), load_references(args.references), predictions, args.method_id
                ),
                args.output,
            )
        elif args.command == "compare":
            from .evaluate import paired_bootstrap

            _emit(
                paired_bootstrap(read_json(args.left), read_json(args.right), resamples=args.resamples),
                args.output,
            )
        elif args.command.startswith("train-"):
            policy = ExecutionPolicy(args.execute_model)
            policy.require_model_execution("Training")  # before dependencies or data are loaded
            from .plan import implementation_hash
            from .train import TrainingConfig
            from .workflow import fit_ranker_from_cache, fit_residue_from_cache

            config = TrainingConfig(**read_json(args.config))
            common = dict(
                output_dir=args.output_dir,
                config=config,
                policy=policy,
                code_sha256=implementation_hash(),
                method_id=args.method_id,
                resume=args.resume,
            )
            if args.command == "train-residue":
                result = fit_residue_from_cache(
                    args.targets, args.references, args.embedding_keys, args.embedding_cache, **common
                )
            else:
                result = fit_ranker_from_cache(
                    args.targets, args.references, args.bundle_index, base_release=args.base_release, **common
                )
            print(json.dumps(result, indent=2, allow_nan=False))
        elif args.command == "predict":
            policy = ExecutionPolicy(args.execute_model)
            policy.require_model_execution("Prediction")
            from .predict import predict_prepared
            from .prepared import read_prepared

            result = predict_prepared(
                read_prepared(args.bundle),
                release_directory=args.release,
                policy=policy,
                device=args.device,
                top_k=args.top_k,
            )
            _emit(asdict(result), args.output)
        return 0
    except (ValueError, FileNotFoundError, ComputeDisabled) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
