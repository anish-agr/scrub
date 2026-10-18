"""Resumable HF -> validation -> training -> matching ready deployment."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from dotenv import set_key

from .dataset_check import local_check
from .perceptron import APIError, Perceptron

ROOT = Path(__file__).resolve().parents[1]
FAILED = {"failed", "cancelled", "canceled", "error", "invalid", "rejected"}
SUCCEEDED = {"succeeded", "success", "completed"}


def status(record):
    return record.get("status", record.get("state"))


def atomic_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ValueError("Pipeline state temporary file already exists; inspect it first")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
    os.replace(temporary, path)


def validation_ok(document):
    if not isinstance(document, dict) or not document:
        raise APIError("Validation returned no evidence; training not submitted")
    def rejected(value):
        if isinstance(value, dict):
            for key, entry in value.items():
                if key in {"errors", "error"} and entry:
                    return True
                if key in {"valid", "passed", "success"} and entry is False:
                    return True
                if key in {"status", "state"} and isinstance(entry, str) and entry in FAILED:
                    return True
                if rejected(entry):
                    return True
        elif isinstance(value, list):
            return any(rejected(entry) for entry in value)
        return False
    if rejected(document):
        raise APIError("Dataset validation reports failure; training not submitted")


def validation_complete(document):
    validation_ok(document)
    complete = {"ready", "valid", "validated", "passed", "succeeded", "completed", "complete", "success"}
    return (any(document.get(key) is True for key in ("valid", "passed", "success")) or
            any(isinstance(document.get(key), str) and document[key] in complete
                for key in ("status", "state", "stage")))


def run_pipeline(args, *, api_factory=Perceptron, emit=print, clock=time.monotonic, sleep=time.sleep):
    # Complete local checks before constructing a client or reading a team key.
    report = local_check(args.root, args.cadence_report)
    emit({"local_check": report})
    if args.check_only:
        return report
    if not args.confirmed_replay or not args.confirmed_hf_matches_local:
        raise ValueError("Pipeline requires --confirmed-replay and --confirmed-hf-matches-local")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo_id or ""):
        raise ValueError("A public HF repo_id (user/scrub) is required")
    if not args.idempotency_key or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.idempotency_key):
        raise ValueError("Use a stable --idempotency-key (1..80 letters/digits/_/-)")
    if not all(math.isfinite(value) and value > 0 for value in (args.interval, args.timeout)):
        raise ValueError("Polling interval and timeout must be positive")
    if not 1 <= args.steps <= 10000 or (args.backend == "shared" and args.mode != "expert_only"):
        raise ValueError("Invalid training settings; shared backend supports expert_only only")
    registration = {"name": args.name, "source_kind": "huggingface",
                    "repo_id": args.repo_id, "revision": args.revision}
    settings = {"backend": args.backend, "mode": args.mode, "action_horizon": 30,
                "rtc_enabled": True, "steps": args.steps}
    spec = {"local": report["fingerprint"], "registration": registration, "training": settings,
            "idempotency_key": args.idempotency_key}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    path = Path(args.state_file or ROOT / f".env.pipeline-{args.idempotency_key}.json")
    state = json.loads(path.read_text()) if path.exists() else {"fingerprint": fingerprint}
    if state.get("fingerprint") != fingerprint:
        raise ValueError("Pipeline inputs changed; do not reuse this run key/state file")
    atomic_json(path, state)
    deadline = clock() + args.timeout

    def poll(read, predicate, label):
        while clock() < deadline:
            record = read()
            if status(record) in FAILED:
                raise APIError(f"{label} failed; inspect its status/validation before a new run")
            if predicate(record):
                return record
            sleep(args.interval)
        raise APIError(f"Pipeline timed out waiting for {label}; rerun with the same key/state to resume")

    api = api_factory()
    try:
        emit({"capabilities": api.capabilities()})
        if not state.get("dataset_id"):
            registered = api.register_dataset(registration, args.idempotency_key + "-dataset")
            state["dataset_id"] = registered["id"]
            atomic_json(path, state)
        dataset_id = state["dataset_id"]
        poll(lambda: api.dataset(dataset_id), lambda record: status(record) == "ready", "dataset")
        validation = poll(lambda: api.validation(dataset_id), validation_complete, "dataset validation")
        emit({"dataset_id": dataset_id, "validation": validation})
        validation_ok(validation)
        if not state.get("job_id"):
            job = api.train({"dataset_id": dataset_id, **settings}, args.idempotency_key + "-job")
            state["job_id"] = job["id"]
            atomic_json(path, state)
        job_id = state["job_id"]
        emit({"job_id": job_id})
        cursors = {"logs": 0, "metrics": 0}

        def read_job():
            job = api.job(job_id)
            for kind in cursors:
                page = getattr(api, kind)(job_id, cursors[kind])
                emit({kind: page})
                cursors[kind] = page.get("next_cursor", cursors[kind])
            return job

        job = poll(read_job, lambda record: status(record) in SUCCEEDED, "training job")
        checkpoint_id = job.get("checkpoint_id") or job.get("artifact_id")
        deployment_id = job.get("deployment_id")
        if checkpoint_id:
            emit({"checkpoint": api.checkpoint(checkpoint_id)})
        if not checkpoint_id and not deployment_id:
            raise APIError("Completed job has no checkpoint_id/artifact_id/deployment_id; cannot select a deployment safely")

        def ready_deployment(record):
            for item in record.get("items", []):
                matches = item.get("id") == deployment_id if deployment_id else item.get("checkpoint_id") == checkpoint_id
                if matches and status(item) == "ready":
                    record["selected"] = item["id"]
                    return True
            return False

        deployments = poll(api.deployments, ready_deployment, "matching ready deployment")
        selected = deployments["selected"]
        # Review/pinning the contract for motion is separate from selecting a model.
        contract = api.contract(selected)
        if not contract.get("contract_id"):
            raise APIError("Ready deployment has no serving contract_id")
        env_path = Path(args.env_file or ROOT / ".env")
        if env_path.is_symlink():
            raise ValueError("Refusing to update a symlink .env")
        set_key(str(env_path), "PERCEPTRON_DEPLOYMENT_ID", selected)
        state["deployment_id"] = selected
        atomic_json(path, state)
        emit({"deployment_id": selected, "contract_id": contract["contract_id"], "env_updated": True})
        return selected
    finally:
        api.close()
