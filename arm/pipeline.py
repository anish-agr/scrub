"""Resumable upload -> validation -> training -> matching ready deployment.

Default source is a direct upload of the exact local snapshot that passed the local
check and QA (arm/upload_dataset.py, no Hugging Face). --source hf registers an
already pushed public HF repo at a pinned revision instead.
"""
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
from .upload_dataset import upload

ROOT = Path(__file__).resolve().parents[1]
FAILED = {"failed", "cancelled", "canceled", "error", "invalid", "rejected"}
SUCCEEDED = {"succeeded", "success", "completed"}
# Validation success words. "ready" is deliberately absent: it is dataset readiness, not a passed validation.
VALIDATED = {"passed", "valid", "validated", "succeeded", "success", "completed"}
IN_PROGRESS = {"uploading", "queued", "pending", "ingesting", "validating", "running", "processing"}
TRANSIENT = (None, 429, 500, 502, 503, 504)  # same set as arm/real_arm.py
BACKOFF_START_S, BACKOFF_MAX_S = 2.0, 30.0


def http_status(error):
    """HTTP status from an APIError ("Perceptron HTTP 503"), None for a transport failure."""
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"HTTP (\d{3})", str(error))
    return int(match.group(1)) if match else None


def retry_after(error):
    """Seconds from a Retry-After the client attached to the error, if any (perceptron.py drops headers today)."""
    value = getattr(error, "retry_after", None)
    if value is None:
        headers = getattr(getattr(error, "response", None), "headers", None) or {}
        value = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(seconds, 0.0), 300.0) if math.isfinite(seconds) else None


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
    validation_ok(document)  # raises on any errors entry, a false flag or a failed status
    if any(document.get(key) is True for key in ("valid", "passed", "success")):
        return True
    marks = [document[key].lower() for key in ("status", "state", "stage") if isinstance(document.get(key), str)]
    if any(mark in VALIDATED for mark in marks):
        return True
    # Only read after the dataset itself is `ready`, which the service reaches only after validating
    # (workshop notes: uploading, queued, ingesting, validating, ready). The body is stage, evidence
    # and errors with no fixed success word, so no errors and no stage still in progress counts.
    return not any(mark in IN_PROGRESS for mark in marks)


def qa_check(root):
    """explore/dataset/qa.py per-episode verdicts, read-only, no report file.

    Mirrors qa.main's loop (including its too-short FAIL) without writing HTML.
    """
    from explore.dataset import qa
    try:
        info, episodes, data = qa.load_meta(str(root))
    except SystemExit as error:
        raise ValueError(f"QA could not read the dataset: {error}") from None
    cams = [k.split(".")[-1] for k, v in info["features"].items() if v.get("dtype") == "video"]
    verdict = {"episodes": 0, "pass": [], "warn": [], "fail": {}}
    for _, row in episodes.iterrows():
        index = int(row["episode_index"])
        frames = data[data["episode_index"] == index].sort_values("frame_index")
        measured, flags, *_ = qa.check_episode(str(root), info, row, frames, cams)
        if measured["frames"] < qa.LEN_MIN_S * info["fps"]:
            flags.append(("FAIL", f"too short: {measured['dur']:.1f} s"))
        verdict["episodes"] += 1
        failed = [text for level, text in flags if level == "FAIL"]
        if failed:
            verdict["fail"][index] = "; ".join(failed)
        elif any(level == "WARN" for level, _ in flags):
            verdict["warn"].append(index)
        else:
            verdict["pass"].append(index)
    return verdict


def accepted_episodes(text):
    if not text:
        return []
    try:
        return sorted({int(part) for part in str(text).split(",") if part.strip()})
    except ValueError:
        raise ValueError("--accept-qa-fail takes episode indexes like 1,5,7") from None


def qa_video_check(root):
    """explore/dataset/qa_video.py local checks only (no API key, no report file)."""
    from explore.dataset import qa_video
    try:
        info, episodes = qa_video.load_episodes(str(root))
    except SystemExit as error:
        raise ValueError(f"qa_video could not read the dataset: {error}") from None
    fps = float(info.get("fps") or 30)
    rows = [qa_video.check_episode(episode, fps, None, 0) for episode in episodes]
    return {"episodes": len(rows),
            "unreadable": {row["episode"]: "; ".join(row["reasons"]) for row in rows if "unreadable" in row["flags"]},
            "dark": [row["episode"] for row in rows if "dark" in row["flags"]]}


def preflight(root, cadence_report, *, qa=None, qa_video=None, accept_qa_fail="", emit=None):
    """local_check + qa + qa_video. Never raises for a bad dataset: every problem is a reason.

    Returns {"ok", "reasons", "warnings", "tasks", "local_check", "qa", "qa_video", "accepted"}.
    Reads only the folder and cadence file; never constructs an API client or reads a key.
    """
    emit = emit or (lambda value: None)
    reasons, warnings = [], []
    result = {"ok": False, "reasons": reasons, "warnings": warnings, "tasks": {},
              "local_check": None, "qa": None, "qa_video": None, "accepted": []}
    try:
        accepted = accepted_episodes(accept_qa_fail)
    except ValueError as error:
        reasons.append(str(error))
        accepted = []
    result["accepted"] = accepted
    try:
        report = local_check(root, cadence_report)
        result["local_check"] = report
        result["tasks"] = report.get("tasks", {})
        emit({"local_check": report})
    except Exception as error:  # noqa: BLE001 - a bad dataset is a FAIL reason, not a crash
        report = None
        reasons.append(f"local_check: {error}" if str(error) else f"local_check: {type(error).__name__}")
    expected = report["episodes"] if report else None

    try:
        verdict = (qa or qa_check)(root)
        result["qa"] = verdict
        emit({"qa": verdict})
        if expected is not None and verdict["episodes"] != expected:
            reasons.append(f"QA read {verdict['episodes']} of {expected} episodes; "
                           "wait for the recorder to finish saving, then rerun")
        blocked = sorted(set(verdict["fail"]) - set(accepted))
        if blocked:
            reasons.append(f"QA FAIL on episodes {blocked}: re-record them, or after a person has "
                           "looked at each one in qa.html pass --accept-qa-fail " + ",".join(map(str, blocked)))
        if verdict.get("warn"):
            warnings.append(f"QA WARN on episodes {sorted(verdict['warn'])}")
    except (Exception, SystemExit) as error:  # noqa: BLE001
        reasons.append(f"qa raised {type(error).__name__}: {error}")

    try:
        video = (qa_video or qa_video_check)(root)
        result["qa_video"] = video
        emit({"qa_video": video})
        if expected is not None and video["episodes"] != expected:
            reasons.append(f"qa_video read {video['episodes']} of {expected} episodes")
        unreadable = sorted(set(video.get("unreadable") or {}) - set(accepted))
        if unreadable:
            reasons.append(f"qa_video unreadable video on episodes {unreadable}: re-record them, or after a "
                           "person has watched each one pass --accept-qa-fail " + ",".join(map(str, unreadable)))
        if video.get("dark"):
            warnings.append(f"qa_video dark camera on episodes {sorted(video['dark'])}")
    except (Exception, SystemExit) as error:  # noqa: BLE001
        reasons.append(f"qa_video raised {type(error).__name__}: {error}")
    result["ok"] = not reasons
    return result


def find(document, *names):
    """First value under any of names, at any depth (capabilities nest quotas and limits)."""
    if isinstance(document, dict):
        for name in names:
            if document.get(name) is not None:
                return document[name]
        for value in document.values():
            found = find(value, *names)
            if found is not None:
                return found
    elif isinstance(document, list):
        for value in document:
            found = find(value, *names)
            if found is not None:
                return found
    return None


def allows(listed, value):
    """A capabilities entry allows value: equal, a list containing it, or a {min, max} range."""
    if isinstance(listed, (list, tuple, set)):
        return value in listed
    if isinstance(listed, dict) and ("min" in listed or "max" in listed):
        low, high = listed.get("min", value), listed.get("max", value)
        return isinstance(low, (int, float)) and isinstance(high, (int, float)) and low <= value <= high
    return listed == value and type(listed) is type(value)


def capabilities_allow(document, settings):
    """Refuse a job the service does not list as allowed (no silent fallback, absent means refused)."""
    if not isinstance(document, dict) or not document:
        raise APIError("Capabilities returned nothing; job not submitted")
    problems = []
    backends = document.get("backends")
    if isinstance(backends, dict):
        backend_ok = settings["backend"] in backends
        modes = backends.get(settings["backend"])
    else:
        backend_ok = isinstance(backends, list) and settings["backend"] in backends
        modes = document.get("modes")
    if not backend_ok:
        problems.append(f"backend {settings['backend']!r} not listed")
    if not allows(modes, settings["mode"]):
        problems.append(f"mode {settings['mode']!r} not listed")
    if not allows(find(document, "action_horizons", "action_horizon"), settings["action_horizon"]):
        problems.append(f"action_horizon {settings['action_horizon']} not listed")
    if settings["rtc_enabled"] is not True or not allows(find(document, "rtc", "rtc_enabled"), True):
        problems.append("rtc true not listed")
    if not allows(find(document, "steps"), settings["steps"]):
        problems.append(f"steps {settings['steps']} not listed")
    quota = find(document, "successful_jobs_per_team")
    if quota is None:
        problems.append("successful_jobs_per_team missing (quota unknown)")
    elif not isinstance(quota, (int, float)) or isinstance(quota, bool) or quota < 1:
        problems.append(f"successful_jobs_per_team is {quota!r}")
    if document.get("ready_for_training") is False:
        problems.append("ready_for_training is false")
    if problems:
        raise APIError("Capabilities do not allow these training settings (" + "; ".join(problems)
                       + "); job not submitted")


def run_pipeline(args, *, api_factory=Perceptron, emit=print, clock=time.monotonic, sleep=time.sleep,
                 qa=None, qa_video=None):
    # The same preflight as `python -m arm.train preflight`, before any client, key, upload or POST.
    checked = preflight(args.root, args.cadence_report, qa=qa, qa_video=qa_video,
                        accept_qa_fail=getattr(args, "accept_qa_fail", ""), emit=emit)
    if not checked["ok"]:
        raise ValueError("PREFLIGHT FAIL: " + " | ".join(checked["reasons"]))
    report, accepted = checked["local_check"], checked["accepted"]
    if args.check_only:
        return report
    source = getattr(args, "source", "upload")
    if source not in {"upload", "hf"}:
        raise ValueError("--source is upload or hf")
    if not args.confirmed_replay:
        raise ValueError("Pipeline requires --confirmed-replay (a person watched episode 0 replay on the arm)")
    if source == "hf":
        if not getattr(args, "confirmed_hf_matches_local", False):
            raise ValueError("--source hf requires --confirmed-hf-matches-local")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo_id or ""):
            raise ValueError("A public HF repo_id (user/scrub) is required")
        if not re.fullmatch(r"[0-9a-f]{40}", args.revision or ""):
            raise ValueError("--source hf needs --revision as the pushed 40-character commit SHA, not a branch")
    if not args.idempotency_key or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.idempotency_key):
        raise ValueError("Use a stable --idempotency-key (1..80 letters/digits/_/-)")
    if not all(math.isfinite(value) and value > 0 for value in (args.interval, args.timeout)):
        raise ValueError("Polling interval and timeout must be positive")
    if not 1 <= args.steps <= 10000 or (args.backend == "shared" and args.mode != "expert_only"):
        raise ValueError("Invalid training settings; shared backend supports expert_only only")
    if source == "hf":
        registration = {"name": args.name, "source_kind": "huggingface",
                        "repo_id": args.repo_id, "revision": args.revision}
    else:
        registration = {"name": args.name, "source_kind": "upload"}
    settings = {"backend": args.backend, "mode": args.mode, "action_horizon": 30,
                "rtc_enabled": True, "steps": args.steps}
    spec = {"local": report["fingerprint"], "registration": registration, "training": settings,
            "idempotency_key": args.idempotency_key, "accepted_qa_fail": accepted}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    path = Path(args.state_file or ROOT / f".env.pipeline-{args.idempotency_key}.json")
    if source == "upload":
        dataset = Path(args.root).resolve()
        for kept in (path, Path(args.env_file or ROOT / ".env")):
            if kept.resolve().is_relative_to(dataset):
                raise ValueError("State and .env files must be outside the dataset folder being uploaded")
    state = json.loads(path.read_text()) if path.exists() else {"fingerprint": fingerprint}
    if state.get("fingerprint") != fingerprint:
        raise ValueError("Pipeline inputs changed; do not reuse this run key/state file")
    atomic_json(path, state)
    deadline = clock() + args.timeout

    def poll(read, predicate, label):
        backoff = BACKOFF_START_S
        while clock() < deadline:
            try:
                record = read()
            except APIError as error:
                # 429/5xx/transport: the job keeps running. Wait and repeat the same GET; never a new
                # POST or idempotency key (that can spend another successful job).
                if http_status(error) not in TRANSIENT:
                    raise
                wait = retry_after(error)
                if wait is None:
                    wait, backoff = backoff, min(backoff * 2, BACKOFF_MAX_S)
                emit({"transient": f"{label}: {error}; retrying the same read in {wait:g} s"})
                sleep(wait)
                continue
            backoff = BACKOFF_START_S
            if status(record) in FAILED:
                raise APIError(f"{label} failed; inspect its status/validation before a new run")
            if predicate(record):
                return record
            sleep(args.interval)
        raise APIError(f"Pipeline timed out waiting for {label}; rerun with the same key/state to resume")

    api = api_factory()
    try:
        capabilities = api.capabilities()
        emit({"capabilities": capabilities})
        if source == "hf" and not state.get("dataset_id"):
            registered = api.register_dataset(registration, args.idempotency_key + "-dataset")
            state["dataset_id"] = registered["id"]
            atomic_json(path, state)
        if source == "upload" and not state.get("uploaded"):
            def registered(dataset_id):
                if state.get("dataset_id") not in (None, dataset_id):
                    raise APIError("Upload registration returned a different dataset id than the state file")
                state["dataset_id"] = dataset_id
                atomic_json(path, state)

            def unchanged():
                if local_check(args.root, args.cadence_report)["fingerprint"] != report["fingerprint"]:
                    raise APIError("Local dataset or cadence changed since the check; do not finalize")

            done = upload(api, args.root, args.name, args.idempotency_key + "-dataset",
                          on_registered=registered, before_finalize=unchanged)
            emit({"dataset_id": done["dataset_id"], "finalize": done["finalize"]})
            state["uploaded"] = True
            atomic_json(path, state)
        dataset_id = state["dataset_id"]
        poll(lambda: api.dataset(dataset_id), lambda record: status(record) == "ready", "dataset")
        validation = poll(lambda: api.validation(dataset_id), validation_complete, "dataset validation")
        emit({"dataset_id": dataset_id, "validation": validation})
        validation_ok(validation)
        if not state.get("job_id"):
            capabilities_allow(capabilities, settings)
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
