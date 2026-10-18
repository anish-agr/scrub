import functools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dotenv import dotenv_values
import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from .dataset_check import local_check
from .kinematics import FEATURES
from .perceptron import APIError
from .pipeline import run_pipeline
from . import upload_dataset

N = 10  # local_check needs at least 10 episodes per task
QA_CLEAN = {"episodes": N, "pass": list(range(N)), "warn": [], "fail": {}}
VIDEO_CLEAN = {"episodes": N, "unreadable": {}, "dark": []}
REST = [0., -100., 90., 0., 0., 50.]  # degrees: shoulder_lift rests near -100


def fixture(root, version="v2.1", n=N, task="pick the hemostat"):
    (root / "meta").mkdir()
    (root / "data/chunk-000").mkdir(parents=True)
    features = {name: {"dtype": "float32", "shape": [6], "names": list(FEATURES)}
                for name in ("observation.state", "action")}
    features.update({"observation.images." + name: {"dtype": "video", "shape": [480, 640, 3]}
                     for name in ("side", "wrist")})
    info = {"codebase_version": version, "fps": 30, "total_episodes": n, "total_frames": 3 * n,
            "features": features}
    (root / "meta/info.json").write_text(json.dumps(info))
    episodes = [{"episode_index": i, "length": 3, "tasks": [task]} for i in range(n)]
    if version.startswith("v2"):
        (root / "meta/episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    else:
        (root / "meta/episodes/chunk-000").mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(episodes), root / "meta/episodes/chunk-000/file-000.parquet")
    rows = [{"episode_index": i, "frame_index": j, "timestamp": j / 30,
             "observation.state": REST, "action": REST}
            for i in range(n) for j in range(3)]
    pq.write_table(pa.Table.from_pylist(rows), root / "data/chunk-000/file-000.parquet")
    cadence = root / "cadence.json"
    cadence.write_text(json.dumps({"episodes": [{"episode_index": i, "measured_fps": 29.88, "use_degrees": True,
                                                  "camera_fps": {"side": 29.9, "wrist": 29.7}} for i in range(n)]}))
    return cadence


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cadence = fixture(self.root)
        self.args = SimpleNamespace(root=self.root, cadence_report=self.cadence,
                                    source="hf", accept_qa_fail="",
                                    check_only=False, confirmed_replay=True, confirmed_hf_matches_local=True,
                                    repo_id="test/scrub", name="scrub", revision="a" * 40,
                                    idempotency_key="run-1", state_file=self.root / "pipeline.json",
                                    env_file=self.root / ".env", backend="standard", mode="expert_only",
                                    steps=1000, interval=.01, timeout=1)
        self.api = Mock()
        self.api.capabilities.return_value = {"backends": {"standard": ["expert_only"]}, "action_horizons": [30],
                                              "rtc": [False, True], "steps": [1000], "ready_for_training": True,
                                              "quotas": {"successful_jobs_per_team": 5}}
        self.api.register_dataset.return_value = {"id": "ds-test"}
        self.api.dataset.return_value = {"status": "ready"}
        self.api.validation.return_value = {"status": "passed", "errors": []}
        self.api.train.return_value = {"id": "job-test"}
        self.api.job.return_value = {"status": "succeeded", "checkpoint_id": "cp-test"}
        self.api.logs.return_value = {"next_cursor": 1}
        self.api.metrics.return_value = {"next_cursor": 2}
        self.api.checkpoint.return_value = {"id": "cp-test", "status": "inference_ready"}
        self.api.deployments.return_value = {"items": [
            {"id": "wrong", "status": "ready", "checkpoint_id": "cp-other"},
            {"id": "dep-test", "status": "ready", "checkpoint_id": "cp-test"}]}
        self.api.contract.return_value = {"contract_id": "contract-test"}
        self.factory = Mock(return_value=self.api)
        self.qa = Mock(return_value=QA_CLEAN)
        self.qa_video = Mock(return_value=VIDEO_CLEAN)

    def run_pipeline(self, **kwargs):
        return run_pipeline(self.args, api_factory=self.factory, emit=lambda value: None, qa=self.qa,
                            qa_video=self.qa_video, sleep=lambda seconds: None, **kwargs)

    def change_info(self, mutate):
        path = self.root / "meta/info.json"
        info = json.loads(path.read_text())
        mutate(info)
        path.write_text(json.dumps(info))

    def test_pipeline_selects_matching_deployment_and_preserves_env(self):
        self.args.env_file.write_text("OTHER='test-value'\nPERCEPTRON_DEPLOYMENT_ID='old'\n")
        self.assertEqual(self.run_pipeline(), "dep-test")
        self.assertEqual(dotenv_values(self.args.env_file), {"OTHER": "test-value", "PERCEPTRON_DEPLOYMENT_ID": "dep-test"})
        self.api.register_dataset.assert_called_once_with(
            {"name": "scrub", "source_kind": "huggingface", "repo_id": "test/scrub", "revision": "a" * 40}, "run-1-dataset")
        self.api.train.assert_called_once_with({"dataset_id": "ds-test", "backend": "standard", "mode": "expert_only",
                                                "action_horizon": 30, "rtc_enabled": True, "steps": 1000}, "run-1-job")
        self.api.close.assert_called_once()
        self.run_pipeline()
        # Same run resumes instead of spending another training submission.
        self.api.register_dataset.assert_called_once()
        self.api.train.assert_called_once()

    def test_check_only_never_constructs_api_or_writes_env(self):
        self.args.check_only = True
        report = self.run_pipeline()
        self.assertEqual(report["episodes"], N)
        self.factory.assert_not_called()
        self.assertFalse(self.args.env_file.exists())

    def test_bad_metadata_blocks_all_network(self):
        for change in (lambda i: i.update(fps=25), lambda i: i.update(total_episodes=1),
                       lambda i: i["features"]["observation.images.side"].update(shape=[448, 448, 3]),
                       lambda i: i["features"]["action"].update(names=["wrong"] * 6)):
            with self.subTest(change=change):
                original = (self.root / "meta/info.json").read_text()
                self.change_info(change)
                with self.assertRaises(ValueError):
                    self.run_pipeline()
                (self.root / "meta/info.json").write_text(original)
        self.factory.assert_not_called()

    def test_cadence_cannot_be_inferred_from_30fps_metadata(self):
        self.cadence.write_text(json.dumps({"episodes": [{"episode_index": 0, "measured_fps": 25},
                                                         {"episode_index": 1, "measured_fps": 30}]}))
        with self.assertRaisesRegex(ValueError, "cadence"):
            self.run_pipeline()
        self.factory.assert_not_called()

    def test_validation_failure_never_trains(self):
        self.api.validation.return_value = {"status": "failed", "errors": ["bad fps"]}
        with self.assertRaises(APIError):
            self.run_pipeline()
        self.api.train.assert_not_called()
        self.assertFalse(self.args.env_file.exists())

    def test_poll_validation_and_cursor_progress(self):
        self.api.validation.side_effect = [{"status": "validating"}, {"status": "passed"}]
        self.api.job.side_effect = [{"status": "running"}, {"status": "succeeded", "checkpoint_id": "cp-test"}]
        self.assertEqual(self.run_pipeline(), "dep-test")
        self.assertEqual(self.api.logs.call_args_list[1].args, ("job-test", 1))
        self.assertEqual(self.api.metrics.call_args_list[1].args, ("job-test", 2))

    def test_changed_snapshot_cannot_reuse_run(self):
        self.run_pipeline()
        self.args.steps = 999
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_pipeline()
        self.factory.assert_called_once()

    def test_wrong_ready_deployment_times_out_without_env_update(self):
        self.api.deployments.return_value = {"items": [{"id": "wrong", "status": "ready", "checkpoint_id": "other"}]}
        self.args.timeout = .03
        with self.assertRaisesRegex(APIError, "matching ready deployment"):
            self.run_pipeline()
        self.assertFalse(self.args.env_file.exists())

    def test_slow_camera_blocks_even_with_good_loop_rate(self):
        data = json.loads(self.cadence.read_text())
        data["episodes"][1]["camera_fps"]["wrist"] = 22.6
        self.cadence.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "wrist camera ran at 22.6"):
            self.run_pipeline()
        del data["episodes"][1]["camera_fps"]
        self.cadence.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "camera_fps"):
            self.run_pipeline()
        self.factory.assert_not_called()

    def test_task_must_be_an_exact_settings_instruction(self):
        path = self.root / "meta/episodes.jsonl"
        for task in ("pick the spatula", "pick up the hemostat"):
            path.write_text("\n".join(json.dumps({"episode_index": i, "length": 3, "tasks": [task]}) for i in range(N)))
            with self.assertRaisesRegex(ValueError, "not an exact"):
                self.run_pipeline()
        self.factory.assert_not_called()

    def test_disallowed_settings_or_branch_revision_never_train(self):
        self.api.capabilities.return_value["steps"] = [500]
        with self.assertRaisesRegex(APIError, "Capabilities"):
            self.run_pipeline()
        self.api.train.assert_not_called()
        if self.args.source == "hf":
            self.args.revision = "main"
            with self.assertRaisesRegex(ValueError, "commit SHA"):
                self.run_pipeline()

    def test_v3_episode_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cadence = fixture(root, "v3.0")
            self.assertEqual(local_check(root, cadence)["frames"], 3 * N)

    def test_missing_data_frames_fail(self):
        path = self.root / "data/chunk-000/file-000.parquet"
        table = pq.ParquetFile(path).read().slice(0, 5)
        pq.write_table(table, path)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_pipeline()
        self.factory.assert_not_called()


class UploadDefaultTests(PipelineTests):
    """The default source: upload the checked local folder, no Hugging Face."""

    def setUp(self):
        super().setUp()
        self.args.source = "upload"
        self.args.repo_id = None
        # State and .env must live outside the folder being uploaded.
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.args.state_file = Path(outside.name) / "pipeline.json"
        self.args.env_file = Path(outside.name) / ".env"
        self.args.confirmed_hf_matches_local = False
        self.puts = []
        self.api.reserve_uploads.side_effect = lambda dataset_id, files: {"files": [
            {"path": f["path"], "url": "https://upload.example/" + f["path"], "method": "PUT", "headers": {}}
            for f in files]}
        self.api.finalize.return_value = {"status": "finalizing"}

        def handler(request):
            self.assertNotIn("authorization", request.headers)
            self.puts.append(request.url.path)
            return httpx.Response(200)
        self.patcher = patch("arm.pipeline.upload", functools.partial(
            upload_dataset.upload, transport=httpx.MockTransport(handler)))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_pipeline_selects_matching_deployment_and_preserves_env(self):
        self.assertEqual(self.run_pipeline(), "dep-test")
        self.api.register_dataset.assert_called_once_with({"name": "scrub", "source_kind": "upload"}, "run-1-dataset")
        self.assertIn("/meta/info.json", self.puts)
        self.assertIn("/data/chunk-000/file-000.parquet", self.puts)
        self.api.finalize.assert_called_once_with("ds-test")
        self.api.train.assert_called_once_with({"dataset_id": "ds-test", "backend": "standard", "mode": "expert_only",
                                                "action_horizon": 30, "rtc_enabled": True, "steps": 1000}, "run-1-job")
        self.assertEqual(dotenv_values(self.args.env_file), {"PERCEPTRON_DEPLOYMENT_ID": "dep-test"})
        puts = len(self.puts)
        self.run_pipeline()
        # Resume: no second upload, finalize or job.
        self.assertEqual(len(self.puts), puts)
        self.api.finalize.assert_called_once()
        self.api.train.assert_called_once()

    def test_hf_confirmation_not_needed_but_replay_is(self):
        self.args.confirmed_replay = False
        with self.assertRaisesRegex(ValueError, "confirmed-replay"):
            self.run_pipeline()
        self.factory.assert_not_called()

    def test_snapshot_change_during_upload_never_finalizes_or_trains(self):
        def handler(request):
            if request.url.path.endswith("info.json"):
                (self.root / "data/chunk-000/extra.parquet").write_bytes(b"new")
            return httpx.Response(200)
        self.patcher.stop()
        with patch("arm.pipeline.upload", functools.partial(upload_dataset.upload, transport=httpx.MockTransport(handler))):
            with self.assertRaisesRegex(APIError, "do not finalize"):
                self.run_pipeline()
        self.patcher.start()
        self.api.finalize.assert_not_called()
        self.api.train.assert_not_called()
        # The dataset id was saved before any bytes moved, so a rerun resumes it.
        self.assertEqual(json.loads(self.args.state_file.read_text())["dataset_id"], "ds-test")

    def test_failed_put_never_finalizes(self):
        self.patcher.stop()
        with patch("arm.pipeline.upload", functools.partial(upload_dataset.upload, transport=httpx.MockTransport(
                lambda request: httpx.Response(500)))):
            with self.assertRaisesRegex(APIError, "do not finalize"):
                self.run_pipeline()
        self.patcher.start()
        self.api.finalize.assert_not_called()
        self.api.train.assert_not_called()

    def test_state_file_inside_dataset_is_refused(self):
        self.args.state_file = self.root / "pipeline.json"
        with self.assertRaisesRegex(ValueError, "outside the dataset"):
            self.run_pipeline()
        self.factory.assert_not_called()


class QAGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cadence = fixture(self.root)
        self.args = SimpleNamespace(root=self.root, cadence_report=self.cadence, check_only=False,
                                    accept_qa_fail="", source="upload", confirmed_replay=True)
        self.factory = Mock()

    def run_pipeline(self, verdict, video=VIDEO_CLEAN):
        return run_pipeline(self.args, api_factory=self.factory, emit=lambda value: None, qa=lambda root: verdict,
                            qa_video=lambda root: video)

    def test_qa_fail_blocks_check_only_and_submission_before_network(self):
        failing = {"episodes": N, "pass": [0], "warn": [], "fail": {1: "frozen"}}
        for check_only in (True, False):
            self.args.check_only = check_only
            with self.assertRaisesRegex(ValueError, r"QA FAIL on episodes \[1\].*--accept-qa-fail 1"):
                self.run_pipeline(failing)
        self.factory.assert_not_called()

    def test_reviewed_fail_can_be_accepted_explicitly(self):
        self.args.check_only = True
        self.args.accept_qa_fail = "1"
        self.assertEqual(self.run_pipeline({"episodes": N, "pass": [0], "warn": [], "fail": {1: "frozen"}})["episodes"], N)

    def test_qa_must_cover_every_episode(self):
        self.args.check_only = True
        with self.assertRaisesRegex(ValueError, "QA read 1 of 10"):
            self.run_pipeline({"episodes": 1, "pass": [0], "warn": [], "fail": {}})

    def test_qa_crash_is_a_fail_reason_not_a_crash(self):
        self.args.check_only = True
        def crash(root):
            raise SystemExit("no readable parquet files")
        with self.assertRaisesRegex(ValueError, "PREFLIGHT FAIL.*qa raised SystemExit"):
            run_pipeline(self.args, api_factory=self.factory, emit=lambda value: None, qa=crash,
                         qa_video=lambda root: VIDEO_CLEAN)
        self.factory.assert_not_called()

    def test_unreadable_video_blocks_upload(self):
        self.args.check_only = False
        with self.assertRaisesRegex(ValueError, r"unreadable video on episodes \[3\]"):
            self.run_pipeline(QA_CLEAN, {"episodes": N, "unreadable": {3: "wrist: video unreadable"}, "dark": []})
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
