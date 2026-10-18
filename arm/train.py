"""Manual training commands. Jobs are submitted only by train or pipeline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from .perceptron import APIError, Perceptron
from .upload_dataset import upload
from .pipeline import run_pipeline


def emit(value):
    print(json.dumps(value, indent=2))


class PublicRunInfo:
    """Publish only explicitly allowed identifiers, never raw API responses.

    run_info.json is intentionally public and may be committed after a real run.
    It is not the private pipeline resume file and contains no credentials.
    """
    def __init__(self, repo_id, path):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id or "") or any(p in {".", ".."} for p in repo_id.split("/")):
            raise ValueError("Public run info needs an HF user/dataset repo id, not a URL or token")
        self.path = Path(path)
        if self.path.is_symlink() or not self.path.parent.is_dir():
            raise ValueError("Run-info parent must exist and destination must not be a symlink")
        if self.path.exists():
            old = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(old, dict) or old.get("kind") != "scrub_robotics_run" or old.get("schema_version") != 1:
                raise ValueError("Existing run-info file is unfamiliar; refusing to overwrite it")
        self.info = {"kind": "scrub_robotics_run", "schema_version": 1,
                     "dataset_url": "https://huggingface.co/datasets/" + repo_id,
                     "job_id": None, "checkpoint_id": None, "deployment_id": None,
                     "status": "training"}

    @staticmethod
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
            raise ValueError("Invalid public resource identifier; nothing unsafe will be published")
        return value

    def save(self):
        if self.path.is_symlink():
            raise ValueError("Run-info destination became a symlink")
        payload = {**self.info, "updated_at": time.time()}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".run-info-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def observe(self, value):
        if isinstance(value, dict) and value.get("job_id"):
            self.info["job_id"] = self.identifier(value["job_id"])
        if isinstance(value, dict) and value.get("deployment_id") and value.get("env_updated") is True:
            # Only the pipeline's final, validated selection makes a deployment ready.
            self.info["deployment_id"] = self.identifier(value["deployment_id"])
            self.info["status"] = "ready" if self.info["checkpoint_id"] else "resolving_checkpoint"
        if self.info["job_id"]:
            self.save()

    def client(self, factory):
        owner, api = self, factory()

        class ObservedClient:
            def __getattr__(self, name):
                return getattr(api, name)

            def job(self, job_id):
                job = api.job(job_id)
                owner.info["job_id"] = owner.identifier(job_id)
                checkpoint_id = job.get("checkpoint_id") or job.get("artifact_id")
                if checkpoint_id:
                    owner.info["checkpoint_id"] = owner.identifier(checkpoint_id)
                if job.get("status", job.get("state")) in {"succeeded", "success", "completed"}:
                    owner.info["status"] = "exporting"
                owner.save()
                return job

            def checkpoint(self, checkpoint_id):
                checkpoint = api.checkpoint(checkpoint_id)
                owner.info["checkpoint_id"] = owner.identifier(checkpoint_id)
                owner.save()
                return checkpoint

            def deployment(self, deployment_id):
                deployment = api.deployment(deployment_id)
                checkpoint_id = deployment.get("checkpoint_id")
                if checkpoint_id:
                    owner.info["checkpoint_id"] = owner.identifier(checkpoint_id)
                return deployment

            def deployments(self):
                deployments = api.deployments()
                # Some jobs identify the deployment instead of their checkpoint.
                # Observe its relationship, but do not select or declare readiness.
                for deployment in deployments.get("items", []):
                    if deployment.get("job_id") == owner.info["job_id"] and deployment.get("checkpoint_id"):
                        owner.info["checkpoint_id"] = owner.identifier(deployment["checkpoint_id"])
                return deployments

        return ObservedClient()


def pipeline_with_run_info(args, *, output=emit, api_factory=None):
    """Wrap the existing pipeline without modifying its file or spending extra jobs."""
    if args.check_only:
        return run_pipeline(args, emit=output)
    publisher = PublicRunInfo(args.repo_id, args.run_info or Path(__file__).with_name("run_info.json"))

    def observe(value):
        publisher.observe(value)
        output(value)

    try:
        result = run_pipeline(args, emit=observe,
                              api_factory=lambda: publisher.client(api_factory or Perceptron))
        # The regular checkpoint path is observed above. If a job only points
        # at a deployment, resolve that public relationship with a read-only GET.
        if publisher.info["deployment_id"] and not publisher.info["checkpoint_id"]:
            api = api_factory() if api_factory else Perceptron()
            try:
                deployment = api.deployment(publisher.info["deployment_id"])
                publisher.info["checkpoint_id"] = publisher.identifier(deployment.get("checkpoint_id"))
                publisher.info["status"] = "ready"
                publisher.save()
            finally:
                api.close()
        return result
    except BaseException:
        if publisher.info["job_id"]:
            publisher.info["status"] = "interrupted"
            publisher.save()
        raise


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
    sub.add_parser("self-test", help="offline tests of public run-info export; no key or training")
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
    pipeline.add_argument("--run-info", help="public identifier JSON (default: arm/run_info.json); no secrets")
    pipeline.add_argument("--backend", choices=["standard", "shared"], default="standard")
    pipeline.add_argument("--mode", choices=["expert_only", "backbone_lora", "full"], default="expert_only")
    pipeline.add_argument("--steps", type=int, default=1000)
    pipeline.add_argument("--interval", type=float, default=5)
    pipeline.add_argument("--timeout", type=float, default=21600)
    pipeline.add_argument("--check-only", action="store_true")
    pipeline.add_argument("--confirmed-replay", action="store_true")
    pipeline.add_argument("--confirmed-hf-matches-local", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "self-test":
        raise SystemExit(self_test())
    api = None
    try:
        if args.command == "pipeline":
            pipeline_with_run_info(args)
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


def self_test():
    """Embedded so this task changes no other agent's arm files."""
    from types import SimpleNamespace
    import unittest
    from unittest.mock import Mock, patch

    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.path = Path(self.temp.name) / "run_info.json"
            self.args = SimpleNamespace(repo_id="scrub-team/scrub", check_only=False, run_info=self.path)
            self.api = Mock()
            self.api.job.return_value = {"status": "succeeded", "checkpoint_id": "cp_test", "ignored_secret": "test-only-do-not-export"}
            self.api.checkpoint.return_value = {"id": "cp_test", "ignored_secret": "test-only-do-not-export"}

        def fake_pipeline(self, args, *, emit, api_factory):
            client = api_factory()
            emit({"job_id": "job_test", "ignored_secret": "test-only-do-not-export"})
            client.job("job_test")
            client.checkpoint("cp_test")
            emit({"deployment_id": "dep_test", "env_updated": True})
            client.close()
            return "dep_test"

        def test_completed_pipeline_exports_only_public_fields(self):
            with patch(__name__ + ".run_pipeline", self.fake_pipeline):
                self.assertEqual(pipeline_with_run_info(self.args, output=lambda value: None, api_factory=lambda: self.api), "dep_test")
            info = json.loads(self.path.read_text())
            self.assertEqual(info["dataset_url"], "https://huggingface.co/datasets/scrub-team/scrub")
            self.assertEqual((info["job_id"], info["checkpoint_id"], info["deployment_id"]), ("job_test", "cp_test", "dep_test"))
            self.assertEqual(info["status"], "ready")
            self.assertNotIn("test-only-do-not-export", self.path.read_text())
            self.assertEqual(set(info), {"kind", "schema_version", "dataset_url", "job_id", "checkpoint_id", "deployment_id", "status", "updated_at"})

        def test_check_only_never_creates_public_artifact(self):
            self.args.check_only = True
            with patch(__name__ + ".run_pipeline", return_value={"checked": True}) as run:
                pipeline_with_run_info(self.args, output=lambda value: None)
            run.assert_called_once()
            self.assertFalse(self.path.exists())

        def test_interrupted_job_is_not_claimed_ready(self):
            def interrupted(args, *, emit, api_factory):
                emit({"job_id": "job_test"})
                raise APIError("offline injected timeout")
            with patch(__name__ + ".run_pipeline", interrupted), self.assertRaises(APIError):
                pipeline_with_run_info(self.args, output=lambda value: None)
            info = json.loads(self.path.read_text())
            self.assertEqual(info["status"], "interrupted")
            self.assertIsNone(info["deployment_id"])

        def test_unfamiliar_file_not_overwritten(self):
            self.path.write_text('{"user_work":true}')
            with self.assertRaises(ValueError):
                PublicRunInfo(self.args.repo_id, self.path)
            self.assertEqual(self.path.read_text(), '{"user_work":true}')

        def test_unsafe_ids_and_repo_urls_are_rejected(self):
            for value in ("https://hf.example/user/repo?token=test", "../repo", "user/repo?token=test"):
                with self.assertRaises(ValueError):
                    PublicRunInfo(value, self.path)
            with self.assertRaises(ValueError):
                PublicRunInfo.identifier("https://gpu.example?token=test")

        def test_job_artifact_alias_and_unready_deployment(self):
            self.api.job.return_value = {"status": "running", "artifact_id": "artifact_test"}
            owner = PublicRunInfo(self.args.repo_id, self.path)
            client = owner.client(lambda: self.api)
            client.job("job_test")
            owner.observe({"deployment_id": "unready", "env_updated": False})
            info = json.loads(self.path.read_text())
            self.assertEqual(info["checkpoint_id"], "artifact_test")
            self.assertIsNone(info["deployment_id"])

        def test_existing_export_is_not_erased_by_preflight_failure(self):
            with patch(__name__ + ".run_pipeline", self.fake_pipeline):
                pipeline_with_run_info(self.args, output=lambda value: None, api_factory=lambda: self.api)
            original = self.path.read_text()
            with patch(__name__ + ".run_pipeline", side_effect=ValueError("offline bad dataset")), self.assertRaises(ValueError):
                pipeline_with_run_info(self.args, output=lambda value: None)
            self.assertEqual(self.path.read_text(), original)

        def test_checkpoint_can_be_resolved_from_selected_deployment(self):
            def deployment_only(args, *, emit, api_factory):
                emit({"job_id": "job_test"})
                emit({"deployment_id": "dep_test", "env_updated": True})
                return "dep_test"
            self.api.deployment.return_value = {"checkpoint_id": "cp_test"}
            with patch(__name__ + ".run_pipeline", deployment_only):
                pipeline_with_run_info(self.args, output=lambda value: None, api_factory=lambda: self.api)
            self.assertEqual(json.loads(self.path.read_text())["checkpoint_id"], "cp_test")
            self.api.train.assert_not_called()

        def test_actual_pipeline_publishes_all_identifiers_without_network(self):
            args = SimpleNamespace(**{**vars(self.args), "root": "unused", "cadence_report": "unused",
                                      "confirmed_replay": True, "confirmed_hf_matches_local": True,
                                      "idempotency_key": "offline-export", "name": "scrub", "revision": "test-commit",
                                      "backend": "standard", "mode": "expert_only", "steps": 1000,
                                      "interval": .01, "timeout": 1,
                                      "state_file": Path(self.temp.name) / "state.json",
                                      "env_file": Path(self.temp.name) / ".env"})
            self.api.capabilities.return_value = {"supported": True}
            self.api.register_dataset.return_value = {"id": "ds_test"}
            self.api.dataset.return_value = {"status": "ready"}
            self.api.validation.return_value = {"status": "passed"}
            self.api.train.return_value = {"id": "job_test"}
            self.api.logs.return_value = {"next_cursor": 1}
            self.api.metrics.return_value = {"next_cursor": 1}
            self.api.deployments.return_value = {"items": [{"id": "dep_test", "checkpoint_id": "cp_test", "status": "ready"}]}
            self.api.contract.return_value = {"contract_id": "contract_test"}
            with patch("arm.pipeline.local_check", return_value={"fingerprint": "test-local-snapshot"}):
                pipeline_with_run_info(args, output=lambda value: None, api_factory=lambda: self.api)
            info = json.loads(self.path.read_text())
            self.assertEqual((info["job_id"], info["checkpoint_id"], info["deployment_id"]), ("job_test", "cp_test", "dep_test"))
            self.assertEqual(info["status"], "ready")
            self.api.train.assert_called_once()

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
