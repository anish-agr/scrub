"""Manual training commands. Jobs are submitted only by train or pipeline."""
from __future__ import annotations

import argparse
import json
import sys
import time

from .perceptron import APIError, Perceptron
from .upload_dataset import upload
from .pipeline import run_pipeline


def emit(value):
    print(json.dumps(value, indent=2))


def follow(api, job_id, interval, timeout):
    deadline = time.monotonic() + timeout
    cursors = {"logs": 0, "metrics": 0}
    while time.monotonic() < deadline:
        job = api.job(job_id)
        emit(job)
        for kind in cursors:
            page = getattr(api, kind)(job_id, cursors[kind])
            emit({kind: page})
            cursors[kind] = page.get("next_cursor", cursors[kind])
        state = job.get("state", job.get("status"))
        if state in {"failed", "cancelled", "canceled"}:
            raise APIError(f"Training ended: {state}")
        if state in {"succeeded", "completed", "success"}:
            checkpoint_id = job.get("checkpoint_id") or job.get("artifact_id")
            if checkpoint_id:
                emit({"checkpoint": api.checkpoint(checkpoint_id)})
            emit({"deployments": api.deployments()})
            return
        time.sleep(interval)
    raise APIError("Follow timed out; training was not cancelled")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capabilities")
    register = sub.add_parser("register-hf")
    register.add_argument("repo_id")
    register.add_argument("--name", required=True)
    register.add_argument("--revision", default="main")
    register.add_argument("--idempotency-key", required=True)
    direct = sub.add_parser("upload")
    direct.add_argument("root")
    direct.add_argument("--name", required=True)
    direct.add_argument("--idempotency-key", required=True)
    status = sub.add_parser("status")
    status.add_argument("kind", choices=["dataset", "job", "checkpoint", "deployment"])
    status.add_argument("id")
    validation = sub.add_parser("validation")
    validation.add_argument("id")
    training = sub.add_parser("train")
    training.add_argument("dataset_id")
    training.add_argument("--idempotency-key", required=True)
    training.add_argument("--backend", choices=["standard", "shared"], default="standard")
    training.add_argument("--mode", choices=["expert_only", "backbone_lora", "full"], default="expert_only")
    training.add_argument("--steps", type=int, default=1000)
    training.add_argument("--confirmed-replay-and-cadence", action="store_true", required=True)
    following = sub.add_parser("follow")
    following.add_argument("id")
    following.add_argument("--interval", type=float, default=5)
    following.add_argument("--timeout", type=float, default=21600)
    sub.add_parser("deployments")
    contract = sub.add_parser("contract")
    contract.add_argument("id")
    pipeline = sub.add_parser("pipeline", help="preflight local export, register HF, validate, train and deploy")
    pipeline.add_argument("root")
    pipeline.add_argument("--cadence-report", required=True)
    pipeline.add_argument("--repo-id")
    pipeline.add_argument("--name", default="scrub")
    pipeline.add_argument("--revision", default="main")
    pipeline.add_argument("--idempotency-key")
    pipeline.add_argument("--state-file")
    pipeline.add_argument("--env-file")
    pipeline.add_argument("--backend", choices=["standard", "shared"], default="standard")
    pipeline.add_argument("--mode", choices=["expert_only", "backbone_lora", "full"], default="expert_only")
    pipeline.add_argument("--steps", type=int, default=1000)
    pipeline.add_argument("--interval", type=float, default=5)
    pipeline.add_argument("--timeout", type=float, default=21600)
    pipeline.add_argument("--check-only", action="store_true")
    pipeline.add_argument("--confirmed-replay", action="store_true")
    pipeline.add_argument("--confirmed-hf-matches-local", action="store_true")
    args = parser.parse_args(argv)
    api = None
    try:
        if args.command == "pipeline":
            run_pipeline(args, emit=emit)
            return
        api = Perceptron()
        if args.command == "capabilities":
            emit(api.capabilities())
        elif args.command == "register-hf":
            emit(api.register_dataset({"name": args.name, "source_kind": "huggingface",
                                       "repo_id": args.repo_id, "revision": args.revision}, args.idempotency_key))
        elif args.command == "upload":
            emit(upload(api, args.root, args.name, args.idempotency_key))
        elif args.command == "status":
            emit(getattr(api, args.kind)(args.id))
        elif args.command == "validation":
            emit(api.validation(args.id))
        elif args.command == "train":
            dataset = api.dataset(args.dataset_id)
            if dataset.get("state", dataset.get("status")) != "ready":
                raise APIError("Dataset must be ready before training")
            # Present the complete evidence before the explicit quota-spending call.
            emit({"validation": api.validation(args.dataset_id), "capabilities": api.capabilities()})
            emit(api.train({"dataset_id": args.dataset_id, "backend": args.backend,
                            "mode": args.mode, "steps": args.steps,
                            "action_horizon": 30, "rtc_enabled": True}, args.idempotency_key))
        elif args.command == "follow":
            if args.interval <= 0 or args.timeout <= 0:
                raise ValueError("Polling interval and timeout must be positive")
            follow(api, args.id, args.interval, args.timeout)
        elif args.command == "deployments":
            emit(api.deployments())
        elif args.command == "contract":
            emit(api.contract(args.id))
    except (APIError, ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if api:
            api.close()


if __name__ == "__main__":
    main()
