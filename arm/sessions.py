"""One instruction per session, reset between runs, new grant after delete."""
from __future__ import annotations

import time
import uuid

import numpy as np

from .perceptron import APIError, Inference, Perceptron
from .streaming import DELAY


class PolicySession:
    def __init__(self, deployment_id, instruction, verified_contract_id):
        self.control = Perceptron()
        self.inference = None
        self.session_id = None
        try:
            contract = self.control.contract(deployment_id)
            self.contract_id = contract["contract_id"]
            if self.contract_id != verified_contract_id:
                raise APIError("Serving contract is not pinned in rig.json; review it before hardware use")
            session_id = "scrub-" + uuid.uuid4().hex
            grant = self.control.grant(deployment_id, session_id)
            if grant["session_id"] != session_id:
                raise APIError("Session grant id mismatch")
            self.inference = Inference(grant)
            self.session_id = session_id
            reply = self.inference.create_session(deployment_id, instruction, self.contract_id)
            if reply["session_id"] != session_id or reply["contract_id"] != self.contract_id:
                raise APIError("Robot session contract/id mismatch")
        except Exception:
            self.close()
            raise

    def predict(self, metadata, images):
        return self.inference.predict(self.session_id, metadata, images["side"], images["wrist"])

    def reset(self):
        self.inference.reset(self.session_id)

    def close(self):
        try:
            if self.inference is not None and self.session_id:
                self.inference.delete(self.session_id)
        except APIError:
            pass  # Local motion is already stopped; remote session also expires.
        finally:
            if self.inference is not None:
                self.inference.close()
            self.control.close()


class DryPolicySession:
    """Protocol fake, not a learned model or simulation of grasp success."""
    contract_id = "dry-run-contract"

    def __init__(self, instruction, latency=0.02):
        self.instruction = instruction
        self.latency = latency
        self.requests = []
        self.reset_count = 0
        self.closed = False

    def predict(self, metadata, images):
        if self.closed:
            raise RuntimeError("Session closed")
        if not all(images[n].startswith(b"\x89PNG") for n in ("side", "wrist")):
            raise ValueError("Expected PNG images")
        self.requests.append(metadata)
        time.sleep(self.latency)
        rows = np.tile(metadata["state"], (30, 1)).astype(float)
        # Close slowly enough that the fake loop also exercises rate limiting.
        rows[:, 5] = 40 if self.instruction.startswith("pick") else 100
        rtc = metadata.get("rtc")
        if rtc:
            rows[:DELAY] = rtc["committed_actions"]
        return {"sequence": metadata["sequence"], "chunk_id": f"dry-{len(self.requests)}",
                "actions": rows.tolist(), "execute_from_index": DELAY if rtc else 0,
                "rtc_applied": bool(rtc), "prefix_length": DELAY if rtc else 0}

    def reset(self):
        self.reset_count += 1

    def close(self):
        self.closed = True
