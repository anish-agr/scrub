import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from dotenv import dotenv_values
import pyarrow as pa
import pyarrow.parquet as pq

from .dataset_check import local_check
from .kinematics import FEATURES
from .perceptron import APIError
from .pipeline import run_pipeline


def fixture(root, version="v2.1"):
    (root / "meta").mkdir()
    (root / "data/chunk-000").mkdir(parents=True)
    features = {name: {"dtype": "float32", "shape": [6], "names": list(FEATURES)}
                for name in ("observation.state", "action")}
    features.update({"observation.images." + name: {"dtype": "video", "shape": [480, 640, 3]}
                     for name in ("side", "wrist")})
    info = {"codebase_version": version, "fps": 30, "total_episodes": 2, "total_frames": 6,
            "features": features}
    (root / "meta/info.json").write_text(json.dumps(info))
    episodes = [{"episode_index": i, "length": 3} for i in range(2)]
    if version.startswith("v2"):
        (root / "meta/episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    else:
        (root / "meta/episodes/chunk-000").mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(episodes), root / "meta/episodes/chunk-000/file-000.parquet")
    rows = [{"episode_index": i, "frame_index": j, "timestamp": j / 30,
             "observation.state": [0.] * 5 + [50.], "action": [0.] * 5 + [50.]}
            for i in range(2) for j in range(3)]
    pq.write_table(pa.Table.from_pylist(rows), root / "data/chunk-000/file-000.parquet")
    cadence = root / "cadence.json"
    cadence.write_text(json.dumps({"episodes": [{"episode_index": i, "measured_fps": 29.88} for i in range(2)]}))
    return cadence


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cadence = fixture(self.root)
        self.args = SimpleNamespace(root=self.root, cadence_report=self.cadence,
                                    check_only=False, confirmed_replay=True, confirmed_hf_matches_local=True,
                                    repo_id="test/scrub", name="scrub", revision="test-commit",
                                    idempotency_key="run-1", state_file=self.root / "pipeline.json",
                                    env_file=self.root / ".env", backend="standard", mode="expert_only",
                                    steps=1000, interval=.01, timeout=1)
        self.api = Mock()
        self.api.capabilities.return_value = {"modes": ["expert_only"]}
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

    def run_pipeline(self, **kwargs):
        return run_pipeline(self.args, api_factory=self.factory, emit=lambda value: None, **kwargs)

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
            {"name": "scrub", "source_kind": "huggingface", "repo_id": "test/scrub", "revision": "test-commit"}, "run-1-dataset")
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
        self.assertEqual(report["episodes"], 2)
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

    def test_v3_episode_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cadence = fixture(root, "v3.0")
            self.assertEqual(local_check(root, cadence)["frames"], 6)

    def test_missing_data_frames_fail(self):
        path = self.root / "data/chunk-000/file-000.parquet"
        table = pq.ParquetFile(path).read().slice(0, 5)
        pq.write_table(table, path)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_pipeline()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
