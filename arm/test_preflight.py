"""Preflight gates before any upload or training POST. No network, no hardware."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pyarrow.parquet as pq

from .dataset_check import local_check
from .perceptron import APIError
from . import pipeline, train
from .test_pipeline import N, QA_CLEAN, VIDEO_CLEAN, fixture


def rewrite_cadence(path, change):
    data = json.loads(path.read_text())
    for entry in data["episodes"]:
        change(entry)
    path.write_text(json.dumps(data))


def rewrite_state(root, state):
    path = root / "data/chunk-000/file-000.parquet"
    rows = pq.ParquetFile(path).read().to_pylist()
    for row in rows:
        row["observation.state"] = row["action"] = state
    import pyarrow as pa
    pq.write_table(pa.Table.from_pylist(rows), path)


class LocalCheckGates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "ds"
        self.root.mkdir()
        self.cadence = fixture(self.root)

    def test_clean_fixture_passes_and_counts_tasks(self):
        report = local_check(self.root, self.cadence)
        self.assertEqual(report["tasks"], {"pick the hemostat": N})

    def test_use_degrees_must_be_true_on_every_cadence_entry(self):
        for value in (None, False, "true", 1):
            with self.subTest(value=value):
                rewrite_cadence(self.cadence, lambda e: e.pop("use_degrees", None) if value is None
                                else e.update(use_degrees=value))
                with self.assertRaisesRegex(ValueError, "use_degrees"):
                    local_check(self.root, self.cadence)

    def test_radians_scale_shoulder_lift_fails(self):
        rewrite_state(self.root, [0.2, -0.4, 0.1, 0., 0., 50.])
        with self.assertRaisesRegex(ValueError, "shoulder_lift"):
            local_check(self.root, self.cadence)
        rewrite_state(self.root, [0., -10., 0., 0., 0., 50.])  # boundary still inside the band
        with self.assertRaisesRegex(ValueError, "shoulder_lift"):
            local_check(self.root, self.cadence)

    def test_ten_episodes_per_task(self):
        path = self.root / "meta/episodes.jsonl"
        tasks = ["pick the hemostat"] * 9 + ["return the hemostat"]
        path.write_text("\n".join(json.dumps({"episode_index": i, "length": 3, "tasks": [t]})
                                  for i, t in enumerate(tasks)))
        with self.assertRaisesRegex(ValueError, r"at least 10 episodes per task.*'pick the hemostat'=9.*'return the hemostat'=1"):
            local_check(self.root, self.cadence)

    def test_camera_fps_and_task_strings_still_checked(self):
        rewrite_cadence(self.cadence, lambda e: e["camera_fps"].update(wrist=28.5))
        with self.assertRaisesRegex(ValueError, "wrist camera ran at 28.5"):
            local_check(self.root, self.cadence)
        rewrite_cadence(self.cadence, lambda e: e["camera_fps"].update(wrist=29.7))
        path = self.root / "meta/episodes.jsonl"
        path.write_text(path.read_text().replace("pick the hemostat", "pick the kelly"))
        with self.assertRaisesRegex(ValueError, "not an exact"):
            local_check(self.root, self.cadence)

    def test_missing_camera_and_wrong_joint_names(self):
        path = self.root / "meta/info.json"
        info = json.loads(path.read_text())
        broken = json.loads(json.dumps(info))
        del broken["features"]["observation.images.wrist"]
        path.write_text(json.dumps(broken))
        with self.assertRaisesRegex(ValueError, "side and wrist"):
            local_check(self.root, self.cadence)
        broken = json.loads(json.dumps(info))
        broken["features"]["observation.state"]["names"] = ["j%d" % i for i in range(6)]
        path.write_text(json.dumps(broken))
        with self.assertRaisesRegex(ValueError, "six named float32 joints"):
            local_check(self.root, self.cadence)


class PreflightCommand(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "ds"
        self.root.mkdir()
        fixture(self.root)
        # The command's default cadence path is <root>-cadence.json.
        (self.root / "cadence.json").rename(Path(f"{self.root}-cadence.json"))

    def run_cli(self, *extra, qa=lambda root: QA_CLEAN, qa_video=lambda root: VIDEO_CLEAN):
        out = io.StringIO()
        with patch("arm.pipeline.qa_check", qa), patch("arm.pipeline.qa_video_check", qa_video), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            train.main(["preflight", str(self.root), *extra])
        return stop.exception.code, out.getvalue().splitlines()

    def test_pass_prints_task_counts_and_pass_line(self):
        code, lines = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn(f"  {N:4d}  pick the hemostat", lines)
        self.assertEqual(lines[-1], "PREFLIGHT PASS")

    def test_fail_lists_every_reason(self):
        rewrite_cadence(Path(f"{self.root}-cadence.json"), lambda e: e.pop("use_degrees"))
        failing = {"episodes": N, "pass": [], "warn": [], "fail": {2: "frozen"}}
        code, lines = self.run_cli(qa=lambda root: failing,
                                   qa_video=lambda root: {"episodes": N, "unreadable": {4: "x"}, "dark": []})
        self.assertEqual(code, 1)
        fail = lines.index("PREFLIGHT FAIL")
        reasons = lines[fail + 1:]
        self.assertEqual(len(reasons), 3)
        self.assertIn("use_degrees", reasons[0])
        self.assertIn("QA FAIL on episodes [2]", reasons[1])
        self.assertIn("unreadable video on episodes [4]", reasons[2])

    def test_qa_tools_raising_is_fail_not_crash(self):
        def boom(root):
            raise KeyError("video_path")
        code, lines = self.run_cli(qa=boom, qa_video=boom)
        self.assertEqual(code, 1)
        self.assertTrue(any("qa raised KeyError" in line for line in lines))
        self.assertTrue(any("qa_video raised KeyError" in line for line in lines))

    def test_real_qa_tools_on_this_fixture_never_crash(self):
        # The fixture has no videos, so the real tools cannot pass it; they must not crash preflight.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            train.main(["preflight", str(self.root)])
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("PREFLIGHT FAIL", out.getvalue())

    def test_explicit_cadence_report_and_accept(self):
        cadence = Path(f"{self.root}-cadence.json").rename(self.root.parent / "elsewhere.json")
        failing = {"episodes": N, "pass": [], "warn": [], "fail": {2: "frozen"}}
        code, lines = self.run_cli("--cadence-report", str(cadence), "--accept-qa-fail", "2",
                                   qa=lambda root: failing)
        self.assertEqual((code, lines[-1]), (0, "PREFLIGHT PASS"))

    def test_preflight_never_builds_a_client(self):
        with patch("arm.train.Perceptron") as client:
            self.run_cli()
        client.assert_not_called()


class Revision(unittest.TestCase):
    def test_commit_sha_only(self):
        self.assertEqual(train.commit_sha("a" * 40), "a" * 40)
        for bad in ("main", "master", "", "A" * 40, "a" * 39, "a" * 41):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                train.commit_sha(bad)

    def test_cli_rejects_branches_and_missing_revision_for_hf(self):
        base = ["pipeline", "/nonexistent", "--cadence-report", "/nonexistent.json", "--source", "hf",
                "--repo-id", "u/scrub"]
        for extra in (["--revision", "main"], ["--revision", "master"], ["--revision", ""], []):
            with self.subTest(extra=extra), patch("arm.train.pipeline_with_run_info") as run, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                train.main(base + extra)
            self.assertEqual(stop.exception.code, 2)
            run.assert_not_called()
        with patch("arm.train.Perceptron") as client, contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            train.main(["register-hf", "u/scrub", "--name", "s", "--idempotency-key", "k", "--revision", "main"])
        client.assert_not_called()

    def test_upload_source_needs_no_revision(self):
        with patch("arm.train.pipeline_with_run_info") as run:
            train.main(["pipeline", "/x", "--cadence-report", "/x.json", "--check-only"])
        self.assertIsNone(run.call_args.args[0].revision)

    def test_run_pipeline_rejects_branch_revision_before_any_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ds"
            root.mkdir()
            cadence = fixture(root)
            factory = Mock()
            for revision in (None, "", "main", "master"):
                args = SimpleNamespace(root=root, cadence_report=cadence, source="hf", accept_qa_fail="",
                                       check_only=False, confirmed_replay=True, confirmed_hf_matches_local=True,
                                       repo_id="u/scrub", revision=revision)
                with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, "commit SHA"):
                    pipeline.run_pipeline(args, api_factory=factory, emit=lambda v: None,
                                          qa=lambda r: QA_CLEAN, qa_video=lambda r: VIDEO_CLEAN)
            factory.assert_not_called()


CAPS = {"backends": {"standard": ["expert_only"]}, "action_horizons": [30], "rtc": [True], "steps": [1000],
        "quotas": {"successful_jobs_per_team": 5}}


class TrainCommand(unittest.TestCase):
    def run_train(self, validation, capabilities=CAPS):
        api = Mock()
        api.dataset.return_value = {"status": "ready"}
        api.validation.return_value = validation
        api.capabilities.return_value = capabilities
        api.train.return_value = {"id": "job"}
        with patch("arm.train.Perceptron", return_value=api), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                train.main(["train", "ds", "--idempotency-key", "k", "--confirmed-replay-and-cadence"])
                code = 0
            except SystemExit as stop:
                code = stop.code
        return code, api

    def test_never_posts_unless_validation_passed(self):
        for validation in ({"status": "passed", "errors": ["fps"]}, {"valid": False, "status": "passed"},
                           {"status": "failed"}, {}, {"stage": "validating"}):
            with self.subTest(validation=validation):
                code, api = self.run_train(validation)
                self.assertEqual(code, 1)
                api.train.assert_not_called()

    def test_posts_when_passed(self):
        for validation in ({"status": "passed", "errors": []}, {"state": "validated"}, {"valid": True},
                           {"success": True}, {"stage": "Succeeded"}, {"status": "completed"}):
            with self.subTest(validation=validation):
                code, api = self.run_train(validation)
                self.assertEqual(code, 0)
                api.train.assert_called_once()

    def test_capabilities_without_quota_never_post(self):
        code, api = self.run_train({"status": "passed"}, {k: v for k, v in CAPS.items() if k != "quotas"})
        self.assertEqual(code, 1)
        api.train.assert_not_called()


class ValidationAndCapabilities(unittest.TestCase):
    def test_in_progress_is_not_validation_success(self):
        # read only after the dataset is ready; a body still validating is not done, a clean one is
        self.assertFalse(pipeline.validation_complete({"stage": "validating"}))
        self.assertFalse(pipeline.validation_complete({"status": "queued", "errors": []}))
        self.assertTrue(pipeline.validation_complete({"stage": "ready", "evidence": {}, "errors": []}))
        with self.assertRaises(APIError):
            pipeline.validation_complete({"status": "passed", "errors": ["x"]})

    def test_capabilities_refusals(self):
        settings = {"backend": "standard", "mode": "expert_only", "action_horizon": 30, "rtc_enabled": True,
                    "steps": 1000}
        pipeline.capabilities_allow(CAPS, settings)
        pipeline.capabilities_allow({"backends": ["standard", "shared"], "modes": ["expert_only"],
                                     "action_horizon": 30, "rtc": True, "steps": {"min": 100, "max": 5000},
                                     "successful_jobs_per_team": 2}, settings)
        bad = [{**CAPS, "backends": {"shared": ["expert_only"]}},
               {**CAPS, "backends": {"standard": ["full"]}},
               {**CAPS, "action_horizons": [16]},
               {**CAPS, "rtc": [False]},
               {k: v for k, v in CAPS.items() if k != "rtc"},
               {**CAPS, "steps": [500]},
               {k: v for k, v in CAPS.items() if k != "quotas"},
               {**CAPS, "quotas": {"successful_jobs_per_team": 0}},
               {}]
        for document in bad:
            with self.subTest(document=document), self.assertRaisesRegex(APIError, "Capabilities"):
                pipeline.capabilities_allow(document, settings)
        with self.assertRaises(APIError):
            pipeline.capabilities_allow(CAPS, {**settings, "rtc_enabled": False})


class PipelineGates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root = base / "ds"
        self.root.mkdir()
        self.cadence = fixture(self.root)
        self.args = SimpleNamespace(root=self.root, cadence_report=self.cadence, source="hf", accept_qa_fail="",
                                    check_only=False, confirmed_replay=True, confirmed_hf_matches_local=True,
                                    repo_id="u/scrub", name="scrub", revision="b" * 40, idempotency_key="run-9",
                                    state_file=base / "state.json", env_file=base / ".env", backend="standard",
                                    mode="expert_only", steps=1000, interval=.01, timeout=60)
        self.api = Mock()
        self.api.capabilities.return_value = CAPS
        self.api.register_dataset.return_value = {"id": "ds"}
        self.api.dataset.return_value = {"status": "ready"}
        self.api.validation.return_value = {"status": "passed"}
        self.api.train.return_value = {"id": "job"}
        self.api.logs.return_value = self.api.metrics.return_value = {"next_cursor": 1}
        self.api.checkpoint.return_value = {}
        self.api.deployments.return_value = {"items": [{"id": "dep", "status": "ready", "checkpoint_id": "cp"}]}
        self.api.contract.return_value = {"contract_id": "c"}
        self.sleeps = []

    def go(self):
        return pipeline.run_pipeline(self.args, api_factory=lambda: self.api, emit=lambda v: None,
                                     qa=lambda r: QA_CLEAN, qa_video=lambda r: VIDEO_CLEAN,
                                     sleep=self.sleeps.append)

    def test_transient_job_errors_retry_same_get_without_new_job(self):
        limited = APIError("Perceptron HTTP 429")
        limited.retry_after = "7"
        self.api.job.side_effect = [APIError("Perceptron HTTP 503"), limited,
                                    APIError("Perceptron control transport failed"), APIError("Perceptron HTTP 502"),
                                    {"status": "running"}, {"status": "succeeded", "checkpoint_id": "cp"}]
        self.assertEqual(self.go(), "dep")
        self.assertEqual(self.sleeps, [2.0, 7.0, 4.0, 8.0, .01])
        self.api.train.assert_called_once()
        self.api.register_dataset.assert_called_once()
        self.assertEqual(self.api.train.call_args.args[1], "run-9-job")
        self.assertTrue(all(call.args == ("job",) for call in self.api.job.call_args_list))

    def test_backoff_caps_at_30_seconds(self):
        self.api.job.side_effect = [APIError("Perceptron HTTP 500")] * 6 + [
            {"status": "succeeded", "checkpoint_id": "cp"}]
        self.go()
        self.assertEqual(self.sleeps, [2.0, 4.0, 8.0, 16.0, 30.0, 30.0])

    def test_non_transient_error_stops_without_new_job(self):
        self.api.job.side_effect = APIError("Perceptron HTTP 404")
        with self.assertRaisesRegex(APIError, "404"):
            self.go()
        self.api.train.assert_called_once()

    def test_capabilities_gate_runs_before_post(self):
        self.api.capabilities.return_value = {**CAPS, "quotas": {}}
        with self.assertRaisesRegex(APIError, "successful_jobs_per_team"):
            self.go()
        self.api.train.assert_not_called()

    def test_preflight_fail_blocks_before_any_client(self):
        rewrite_cadence(self.cadence, lambda e: e.update(use_degrees=False))
        factory = Mock()
        for check_only, source in ((False, "hf"), (False, "upload"), (True, "upload")):
            self.args.check_only, self.args.source = check_only, source
            with self.subTest(check_only=check_only, source=source), \
                    self.assertRaisesRegex(ValueError, "PREFLIGHT FAIL.*use_degrees"):
                pipeline.run_pipeline(self.args, api_factory=factory, emit=lambda v: None,
                                      qa=lambda r: QA_CLEAN, qa_video=lambda r: VIDEO_CLEAN)
        factory.assert_not_called()

    def test_pipeline_uses_the_same_preflight(self):
        with patch("arm.pipeline.preflight", wraps=pipeline.preflight) as check:
            self.args.check_only = True
            self.go()
        check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
