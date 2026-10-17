import json
import tempfile
import unittest
from pathlib import Path

import httpx

from .perceptron import APIError, Inference, Perceptron, USER_AGENT
from .upload_dataset import batches, manifest, put_file


class ClientTests(unittest.TestCase):
    def test_control_calls_match_schema(self):
        schema = json.loads((Path(__file__).resolve().parents[1] /
                             "docs/perceptron-openapi.json").read_text())
        calls = []

        def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer test-control")
            self.assertEqual(request.headers["user-agent"], USER_AGENT)
            calls.append(request)
            return httpx.Response(200, json={})

        api = Perceptron("test-control", transport=httpx.MockTransport(handler))
        try:
            api.capabilities()
            api.register_dataset({"name": "test", "source_kind": "upload"}, "stable-dataset")
            self.assertEqual(calls[-1].headers["idempotency-key"], "stable-dataset")
            api.reserve_uploads("ds", [])
            api.finalize("ds")
            api.dataset("ds")
            api.validation("ds")
            api.train({"dataset_id": "ds"}, "stable-job")
            self.assertEqual(calls[-1].headers["idempotency-key"], "stable-job")
            api.jobs()
            api.job("job")
            api.cancel("job")
            api.logs("job", 7)
            self.assertEqual(calls[-1].url.params["cursor"], "7")
            api.metrics("job", 9)
            api.checkpoint("checkpoint")
            api.deployments()
            api.deployment("deployment")
            api.contract("deployment")
            api.grant("deployment", "session")
            for call in calls:
                parts = call.url.path.split("/")
                if len(parts) >= 4:
                    parts[3] = "{identity}"
                route = "/".join(parts)
                self.assertIn(call.method.lower(), schema["paths"][route])
            with self.assertRaises(ValueError):
                api.request("GET", "/v1/inference/health")
        finally:
            api.close()

    def test_inference_routes_multipart_and_credentials(self):
        calls = []

        def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer application-test")
            self.assertEqual(request.headers["modal-authorization"], "Bearer modal-test")
            self.assertNotIn(b"test-control", request.content)
            calls.append(request)
            return httpx.Response(200, json={})

        client = Inference({"endpoint_url": "https://gpu.example/v1/inference",
                            "application_session_token": "application-test",
                            "modal_session_token": "modal-test"},
                           transport=httpx.MockTransport(handler))
        try:
            client.contract("dep")
            client.create_session("dep", "pick the hemostat", "contract")
            client.predict("session", {"sequence": 0}, b"side-image", b"wrist-image")
            self.assertIn(b'name="metadata"', calls[-1].content)
            self.assertIn(b"side-image", calls[-1].content)
            self.assertIn(b"wrist-image", calls[-1].content)
            client.reset("session")
            client.delete("session")
            self.assertEqual(calls[-1].url.path, "/v1/inference/sessions/session")
        finally:
            client.close()

    def test_errors_do_not_echo_secrets(self):
        client = Perceptron("secret-test", transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": "secret-test"})))
        try:
            with self.assertRaisesRegex(APIError, "HTTP 401") as caught:
                client.capabilities()
            self.assertNotIn("secret-test", str(caught.exception))
        finally:
            client.close()

    def test_upload_manifest_and_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "meta/info.json"):
                manifest(root)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text("{}")
            files = manifest(root)
            self.assertEqual(files[0]["size_bytes"], 2)
            self.assertEqual(len(files[0]["sha256"]), 64)
            self.assertEqual([len(b) for b in batches(files * 501)], [500, 1])
            (root / "bad.txt").write_text("invalid")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                manifest(root)

    def test_upload_303_get_has_no_body_or_auth(self):
        calls = []

        def handler(request):
            calls.append(request)
            self.assertNotIn("authorization", request.headers)
            if request.method == "PUT":
                return httpx.Response(303, headers={"Location": "https://upload.example/poll?sig=test"})
            self.assertEqual(request.content, b"")
            self.assertNotIn("x-upload", request.headers)
            return httpx.Response(200)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.json"
            path.write_bytes(b"{}")
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                put_file(client, {"url": "https://upload.example/put", "headers": {"X-Upload": "test"}}, path)
        self.assertEqual([r.method for r in calls], ["PUT", "GET"])


if __name__ == "__main__":
    unittest.main()
