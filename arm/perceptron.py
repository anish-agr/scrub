"""Perceptron control/inference clients; credentials never cross API boundaries."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv

USER_AGENT = "Scrub-DubHacks2026/0.1 (anish-agr/dubhacks-2026; SO-101)"
BASE_URL = "https://robotics.perceptron.inc"


class APIError(RuntimeError):
    """Deliberately excludes response bodies and credential-bearing URLs."""


def identity(value: str) -> str:
    return quote(value, safe="")


def result(response: httpx.Response):
    if not response.is_success:
        raise APIError(f"Perceptron HTTP {response.status_code}")
    return response.json() if response.content else None


class Perceptron:
    def __init__(self, key: str | None = None, *, base_url: str = BASE_URL,
                 transport=None):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        key = key or os.getenv("PERCEPTRON_TEAM_API_KEY")
        if not key:
            raise APIError("Missing PERCEPTRON_TEAM_API_KEY in the repository .env")
        if urlparse(base_url).scheme != "https":
            raise ValueError("Control API requires HTTPS")
        self.http = httpx.Client(base_url=base_url, timeout=30,
                                 follow_redirects=False, transport=transport,
                                 headers={"Authorization": f"Bearer {key}",
                                          "User-Agent": USER_AGENT})

    def close(self):
        self.http.close()

    def request(self, method, path, *, body=None, idempotency_key=None, params=None):
        if not path.startswith("/v1/") or path.startswith("/v1/inference"):
            raise ValueError("Not a control API path")
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            return result(self.http.request(method, path, json=body,
                                           headers=headers, params=params))
        except httpx.HTTPError:
            raise APIError("Perceptron control transport failed") from None

    def capabilities(self):
        return self.request("GET", "/v1/capabilities")

    def register_dataset(self, body, idempotency_key):
        if not idempotency_key:
            raise ValueError("A stable Idempotency-Key is required")
        return self.request("POST", "/v1/datasets", body=body,
                            idempotency_key=idempotency_key)

    def reserve_uploads(self, dataset_id, files):
        return self.request("POST", f"/v1/datasets/{identity(dataset_id)}/uploads",
                            body={"files": files})

    def finalize(self, dataset_id):
        return self.request("POST", f"/v1/datasets/{identity(dataset_id)}/finalize")

    def dataset(self, dataset_id):
        return self.request("GET", f"/v1/datasets/{identity(dataset_id)}")

    def validation(self, dataset_id):
        return self.request("GET", f"/v1/datasets/{identity(dataset_id)}/validation")

    def train(self, body, idempotency_key):
        if not idempotency_key:
            raise ValueError("A stable Idempotency-Key is required")
        return self.request("POST", "/v1/jobs", body=body,
                            idempotency_key=idempotency_key)

    def jobs(self):
        return self.request("GET", "/v1/jobs")

    def job(self, job_id):
        return self.request("GET", f"/v1/jobs/{identity(job_id)}")

    def cancel(self, job_id):
        return self.request("POST", f"/v1/jobs/{identity(job_id)}/cancel")

    def logs(self, job_id, cursor=0):
        return self.request("GET", f"/v1/jobs/{identity(job_id)}/logs", params={"cursor": cursor})

    def metrics(self, job_id, cursor=0):
        return self.request("GET", f"/v1/jobs/{identity(job_id)}/metrics", params={"cursor": cursor})

    def checkpoint(self, checkpoint_id):
        return self.request("GET", f"/v1/checkpoints/{identity(checkpoint_id)}")

    def deployments(self):
        return self.request("GET", "/v1/deployments")

    def deployment(self, deployment_id):
        return self.request("GET", f"/v1/deployments/{identity(deployment_id)}")

    def contract(self, deployment_id):
        return self.request("GET", f"/v1/deployments/{identity(deployment_id)}/contract")

    def grant(self, deployment_id, session_id, ttl_seconds=21600):
        return self.request("POST", f"/v1/deployments/{identity(deployment_id)}/sessions",
                            body={"session_id": session_id, "ttl_seconds": ttl_seconds})


class Inference:
    """One grant per client. No control key, cookies, or automatic retries."""

    def __init__(self, grant, *, transport=None):
        endpoint = grant.get("endpoint_url") or BASE_URL + "/v1/inference"
        if urlparse(endpoint).scheme != "https":
            raise ValueError("Inference endpoint requires HTTPS")
        self.http = httpx.Client(base_url=endpoint.rstrip("/") + "/", timeout=0.4,
                                 follow_redirects=False, transport=transport,
                                 headers={"User-Agent": USER_AGENT,
                                          "Authorization": "Bearer " + grant["application_session_token"],
                                          "Modal-Authorization": "Bearer " + grant["modal_session_token"]})

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        try:
            return result(self.http.request(method, path, **kwargs))
        except httpx.HTTPError:
            raise APIError("Perceptron inference transport failed") from None

    def contract(self, deployment_id):
        return self.request("GET", f"deployments/{identity(deployment_id)}/contract")

    def create_session(self, deployment_id, instruction, contract_id):
        return self.request("POST", f"deployments/{identity(deployment_id)}/sessions",
                            json={"instruction": instruction, "rtc_enabled": True,
                                  "contract_id": contract_id})

    def predict(self, session_id, metadata, side: bytes, wrist: bytes):
        return self.request("POST", f"sessions/{identity(session_id)}/predict",
                            data={"metadata": json.dumps(metadata)},
                            files={"side": ("side.png", side, "image/png"),
                                   "wrist": ("wrist.png", wrist, "image/png")})

    def reset(self, session_id):
        return self.request("POST", f"sessions/{identity(session_id)}/reset")

    def delete(self, session_id):
        return self.request("DELETE", f"sessions/{identity(session_id)}")
