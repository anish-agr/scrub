"""Operator-gated trial matrix (the old PLAN.md rows) over HTTP; no direct arm access.

python -m controller.trials --plan-only
python -m controller.trials --self-test
python -m controller.trials --settings surgical --items hemostat --lighting normal --actions handover --tries 2
python -m controller.trials --settings surgical --actions handover --lighting normal --tries 10 --methods taught_adjusted,ik

Real trials require physical confirmation and call this checkout's ledger.log_test.
--practice requires a fake/sim controller and never writes measured ledger trials.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ("surgical", "dental", "bench")
LIGHTS = ("bright", "normal", "dim")


@dataclass(frozen=True)
class Trial:
    setting: str
    item: str
    lighting: str
    action: str
    attempt: int
    sharp: bool = False
    method: str | None = None  # --skills smart: force this grasp method (model, taught_adjusted, ik, taught)


def build_plan(catalog, *, settings=None, items=None, lighting=None, actions=None, tries=None, methods=None):
    settings, actions = settings or list(SETTINGS), actions or ["handover", "return"]
    if set(settings) - set(SETTINGS) or set(actions) - {"handover", "return"}:
        raise ValueError("Unknown setting or action")
    if lighting and set(lighting) - set(LIGHTS):
        raise ValueError("Lighting must be bright, normal or dim")
    if methods and set(methods) - {"model", "taught", "taught_adjusted", "ik"}:
        raise ValueError("Methods must be model, taught, taught_adjusted or ik")
    if tries is not None and tries < 1:
        raise ValueError("--tries must be positive")
    known = {item["id"] for setting in settings for item in catalog[setting]["items"]}
    if items and set(items) - known:
        raise ValueError("An item filter is not in the selected settings")
    result = []
    for action in actions:
        for setting in settings:
            default_lights = list(LIGHTS) if setting == "surgical" else ["normal", "bright"]
            labels = [label for label in default_lights if not lighting or label in lighting]
            if action == "return":
                labels = ["normal" if not lighting or "normal" in lighting else lighting[0]]
            count = tries if tries is not None else (10 if action == "handover" and setting == "surgical" else 5)
            for label in labels:
                for item in catalog[setting]["items"]:
                    if not items or item["id"] in items:
                        result.extend(Trial(setting, item["id"], label, action, n, bool(item.get("sharp")), method)
                                      for method in (methods or [None]) for n in range(1, count + 1))
    if not result:
        raise ValueError("Filters select no trials")
    return result


class TrialAbort(RuntimeError):
    """Hold/stop or an uncertain command prevents subsequent trials."""


def request(client, method, path, body=None):
    response = client.request(method, path, **({"json": body} if body is not None else {}))
    response.raise_for_status()
    payload = response.json()
    expected = list if path.startswith("/events/recent") else dict
    if not isinstance(payload, expected):
        raise TrialAbort("Malformed controller response; inspect before continuing")
    return payload


def check_mode(state, practice):
    if type(state.get("fake_arm")) is not bool:
        raise TrialAbort("Controller must report fake_arm explicitly")
    if state["fake_arm"] != practice:
        raise TrialAbort("Mode mismatch: --practice is only for fake/sim; measured trials require a real controller")


def stop(client):
    try:
        request(client, "POST", "/stop")
    except (httpx.HTTPError, ValueError, TrialAbort):
        pass  # Report uncertainty; never claim the stop reached the hardware.


def summarize(trial, events, completed):
    kinds = {event.get("type") for event in events}
    retries = max((event.get("retries") for event in events
                   if type(event.get("retries")) is int and event["retries"] >= 0), default=0)
    seconds = next((event["request_to_hand_s"] for event in events
                    if event.get("type") in {"handed", "set_down"} and
                    isinstance(event.get("request_to_hand_s"), (float, int)) and
                    math.isfinite(event["request_to_hand_s"]) and event["request_to_hand_s"] >= 0), None)
    terminal = ("returned" in kinds if trial.action == "return" else
                "set_down" in kinds if trial.sharp else {"handed", "released"} <= kinds)
    # A successful retry is a success with retries>0. A fallback safe set-down
    # of a non-sharp tool is not a successful hand-to-hand delivery.
    success = completed and terminal and not ({"stopped", "error"} & kinds)
    return bool(success), retries, seconds if trial.action == "handover" else None


def run_one(client, trial, *, practice, timeout=90, interval=.1, clock=time.monotonic, sleep=time.sleep):
    command_id = uuid.uuid4().hex
    events, seen = [], set()
    started = clock()
    result = {**asdict(trial), "command_id": command_id, "success": False,
              "retries": 0, "seconds": None, "elapsed_s": 0., "aborted": False}
    try:
        body = {"id": command_id, "action": trial.action, "item": trial.item, "source": "keyboard", "t": time.time()}
        if trial.method:
            body["method"] = trial.method
        reply = request(client, "POST", "/command", body)
        if reply.get("accepted") is not True:
            result["reason"] = "rejected: " + str(reply.get("reason"))
            return result
        pulled = False
        while clock() - started < timeout:
            # Events before state: between the worker taking the job and its first step, /state still reads idle
            # with an empty queue. Read the other way round, a step event fetched after that idle state ended
            # the trial at once (practice --tries 2 scored 1/2 on the fake arm).
            recent = request(client, "GET", "/events/recent?n=500")
            state = request(client, "GET", "/state")
            check_mode(state, practice)
            for event in recent:
                if not isinstance(event, dict):
                    raise TrialAbort("Malformed controller event")
                if event.get("command_id") != command_id:
                    continue
                key = json.dumps(event, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    events.append(event)
            if state.get("step") in {"stopped", "error"}:
                result.update(reason="controller stopped/error: inspect and reset manually", aborted=True)
                break
            if practice and state.get("step") == "waiting_for_pull" and not pulled:
                request(client, "POST", "/command", {"action": "got_it", "source": "keyboard"})
                pulled = True
            active = any(event.get("type") != "command" for event in events)
            if active and state.get("step") == "idle" and not state.get("queue"):
                result["success"], result["retries"], result["seconds"] = summarize(trial, events, True)
                result["reason"] = "controller completed" if result["success"] else "expected completion event missing"
                break
            sleep(interval)
        else:
            stop(client)
            result.update(reason="timeout; stop requested, inspect physical arm", aborted=True)
    except (httpx.HTTPError, ValueError, TrialAbort, KeyboardInterrupt) as error:
        stop(client)
        result.update(reason=f"{type(error).__name__}; stop requested, inspect physical arm", aborted=True)
    finally:
        result["elapsed_s"] = max(0., clock() - started)
        _, result["retries"], result["seconds"] = summarize(trial, events, False)
    return result


def execute(client, plan, *, practice=False, automatic=False, timeout=90, interval=.1,
            read=input, write=print, journal=lambda row: None, log_test=None,
            bench_start=None, clock=time.monotonic, sleep=time.sleep):
    if automatic and not practice:
        raise ValueError("--yes is permitted only for practice, never real trials")
    state = request(client, "GET", "/state")
    check_mode(state, practice)
    if state.get("step") != "idle" or state.get("queue"):
        raise TrialAbort("Start only when idle with an empty queue; reset a stop/error manually")
    if not practice and log_test is None:
        from ledger import log_test
    results, adoption_recorded = [], False
    for number, trial in enumerate(plan, 1):
        how = f" via {trial.method}" if trial.method else ""
        write(f"[{number}/{len(plan)}] {trial.setting} {trial.lighting} {trial.action} {trial.item}{how} #{trial.attempt}")
        try:
            if not automatic:
                prompt = ("Place item in RETURN SPOT" if trial.action == "return" else "Restore item to its tray slot")
                answer = read(prompt + "; set lighting, check full inventory/clearance. Enter=ready (setting switch clears count), q=quit: ").strip().lower()
                if answer == "q":
                    break
                if answer:
                    raise TrialAbort("Unrecognized readiness response; no command sent")
        except (EOFError, KeyboardInterrupt):
            break  # No trial was sent, so no fabricated failed attempt is logged.
        state = request(client, "GET", "/state")
        check_mode(state, practice)
        if state.get("step") != "idle" or state.get("queue"):
            raise TrialAbort("Controller became busy/stopped; no trial sent")
        if state.get("setting") != trial.setting:
            setting = request(client, "POST", "/setting", {"setting": trial.setting})
        else:
            setting = request(client, "GET", "/setting")
        if not any(item.get("id") == trial.item and bool(item.get("sharp")) == trial.sharp for item in setting.get("items", [])):
            raise TrialAbort("Live setting item/sharpness differs from the local plan")
        request(client, "POST", "/lighting", {"lighting": trial.lighting, "lux": None})
        result = run_one(client, trial, practice=practice, timeout=timeout, interval=interval, clock=clock, sleep=sleep)
        result.update(practice=practice, t=time.time(), physical_confirmed=False)
        write(f"Controller: {result['reason']}; retries={result['retries']}; request-to-hand/zone={result['seconds']}")
        if result["success"] and not practice:
            try:
                answer = read("Physically correct handle-first delivery / safe sharp set-down / item back in slot? s=success, f=failure, q=abort: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "q"
            result["physical_confirmed"] = answer == "s"
            result["success"] = answer == "s"
            if answer == "f":
                result["reason"] = "operator rejected the physical outcome"
            if answer not in {"s", "f"}:
                result.update(reason="operator aborted/unconfirmed; not counted as success", aborted=True)
        journal({"type": "trial", **result})
        if not practice:
            log_test(item=trial.item, setting=trial.setting, lighting=trial.lighting,
                     success=result["success"], seconds=result["seconds"], retries=result["retries"])
        results.append(result)
        if result["success"] and trial.setting == "bench" and trial.action == "handover" and not adoption_recorded:
            if bench_start is not None:
                journal({"type": "bench_adoption", "practice": practice,
                         "minutes_since_first_demo": (result["t"] - bench_start) / 60,
                         "command_id": result["command_id"], "t": result["t"]})
            adoption_recorded = True
        if result["aborted"]:
            break
    return results


def split(value):
    return list(dict.fromkeys(v.strip() for v in value.split(",") if v.strip())) if value else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--settings", help="comma-separated surgical,dental,bench")
    parser.add_argument("--items", help="comma-separated item ids")
    parser.add_argument("--lighting", help="comma-separated bright,normal,dim")
    parser.add_argument("--actions", help="comma-separated handover,return")
    parser.add_argument("--tries", type=int, help="override N for selected rows")
    parser.add_argument("--methods", help="comma-separated model,taught_adjusted,ik,taught: N tries per method (controller in --skills smart)")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--interval", type=float, default=.1)
    parser.add_argument("--journal", type=Path, help="new local JSONL file; never overwritten")
    parser.add_argument("--bench-start", help="timezone-aware ISO timestamp of first bench demo, for adoption minutes")
    parser.add_argument("--practice", action="store_true", help="fake/sim only; never log measured ledger trials")
    parser.add_argument("--yes", action="store_true", help="no prompts, practice only")
    parser.add_argument("--plan-only", action="store_true", help="no HTTP, ledger or device access")
    parser.add_argument("--self-test", action="store_true", help="offline tests embedded in this file")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not all(math.isfinite(v) and v > 0 for v in (args.timeout, args.interval)):
        parser.error("timeout and interval must be positive finite seconds")
    if args.yes and not args.practice:
        parser.error("--yes requires --practice")
    from .settings import load
    try:
        catalog = {setting: load(setting) for setting in SETTINGS}
        plan = build_plan(catalog, settings=split(args.settings), items=split(args.items),
                          lighting=split(args.lighting), actions=split(args.actions), tries=args.tries,
                          methods=split(args.methods))
        print(json.dumps({"trials": len(plan), "by_setting_action": dict(Counter(f"{t.setting}/{t.action}" for t in plan))}, indent=2))
        if args.plan_only:
            return 0
        bench_start = None
        if args.bench_start:
            stamp = datetime.fromisoformat(args.bench_start.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.timestamp() > time.time():
                raise ValueError("bench-start needs a timezone and cannot be in the future")
            bench_start = stamp.timestamp()
        path = args.journal or ROOT / f".env.trials-{uuid.uuid4().hex}.jsonl"
        if path.is_symlink():
            raise ValueError("Refusing a symlink journal")
        with path.open("x", encoding="utf-8") as stream, httpx.Client(base_url=args.url, timeout=5) as client:
            def journal(row):
                stream.write(json.dumps(row) + "\n")
                stream.flush()
            print(f"Journal: {path}. No automatic reset/rearm. Real release is by pull/voice/dashboard, not this runner.")
            rows = execute(client, plan, practice=args.practice, automatic=args.yes,
                           timeout=args.timeout, interval=args.interval, journal=journal, bench_start=bench_start)
        good = sum(row["success"] for row in rows)
        print(f"{'PRACTICE' if args.practice else 'MEASURED'}: {good}/{len(rows)} attempted trials successful; {len(plan) - len(rows)} not attempted")
        return 0 if len(rows) == len(plan) and good == len(rows) else 1
    except (httpx.HTTPError, OSError, ValueError, TrialAbort) as error:
        print(f"Trials stopped ({type(error).__name__}): inspect state/journal before continuing")
        return 1


def self_test():
    """Tests live here because no other controller file is in this task's scope."""
    import unittest
    from unittest.mock import Mock

    catalog = {setting: {"id": setting, "items": [{"id": f"{setting}_{n}", "sharp": n == 0}
                                                  for n in range(3)]} for setting in SETTINGS}

    class Harness:
        def __init__(self, *, practice=False, scenario="success"):
            self.practice, self.scenario = practice, scenario
            self.cid, self.action, self.item = None, None, None
            self.calls = []
            self.now = 0.
            self.setting = "surgical"

        def request(self, req):
            self.calls.append((req.method, req.url.path))
            if req.url.path == "/command":
                body = json.loads(req.content)
                self.cid, self.action, self.item = body.get("id"), body["action"], body.get("item")
                return httpx.Response(200, json={"accepted": self.scenario != "rejected", "reason": "test rejection"})
            if req.url.path == "/state":
                step = "picking" if self.cid and self.scenario == "timeout" else "idle"
                if self.cid and self.scenario == "stopped":
                    step = "stopped"
                return httpx.Response(200, json={"step": step, "queue": [], "setting": self.setting, "fake_arm": self.practice})
            if req.url.path == "/setting":
                if req.method == "POST":
                    self.setting = json.loads(req.content)["setting"]
                return httpx.Response(200, json=catalog[self.setting])
            if req.url.path == "/events/recent":
                events = [{"command_id": "unrelated", "type": "released", "t": 0}]
                if self.cid:
                    kinds = (["step"] if self.scenario == "timeout" else
                             ["handed", "released"] if self.action == "handover" else ["returned"])
                    if self.scenario == "fallback":
                        kinds = ["set_down"]
                    if self.scenario == "retry":
                        kinds = ["missed", "handed", "released"]
                    events += [{"command_id": self.cid, "type": kind, "t": n + 1,
                                "request_to_hand_s": 2.5 if kind in {"handed", "set_down"} else None,
                                "retries": 1 if self.scenario == "retry" else 0} for n, kind in enumerate(kinds)]
                return httpx.Response(200, json=events)
            return httpx.Response(200, json={"ok": True})

        def client(self):
            return httpx.Client(base_url="https://offline.test", transport=httpx.MockTransport(self.request))

        def sleep(self, seconds):
            self.now += seconds

    class Tests(unittest.TestCase):
        def test_default_matrix(self):
            plan = build_plan(catalog)
            self.assertEqual(len(plan), 195)
            self.assertEqual(sum(t.action == "return" for t in plan), 45)
            self.assertEqual(sum(t.action == "handover" and t.setting == "surgical" for t in plan), 90)
            self.assertEqual(sum(t.action == "handover" and t.setting != "surgical" for t in plan), 60)

        def test_filters_and_validation(self):
            self.assertEqual(len(build_plan(catalog, settings=["surgical"], items=["surgical_1"], lighting=["dim"], actions=["handover"], tries=2)), 2)
            plan = build_plan(catalog, settings=["surgical"], items=["surgical_1"], lighting=["dim"], actions=["handover"],
                              tries=2, methods=["taught_adjusted", "ik"])
            self.assertEqual([t.method for t in plan], ["taught_adjusted", "taught_adjusted", "ik", "ik"])
            for kwargs in ({"tries": 0}, {"items": ["missing"]}, {"lighting": ["night"]}, {"methods": ["magic"]}):
                with self.assertRaises(ValueError):
                    build_plan(catalog, **kwargs)

        def trial(self, **overrides):
            return Trial(**{"setting": "surgical", "item": "surgical_1", "lighting": "normal",
                            "action": "handover", "attempt": 1, **overrides})

        def execute_one(self, harness, answers=("", "s"), **kwargs):
            replies, self.rows, self.logger = iter(answers), [], Mock()
            with harness.client() as client:
                return execute(client, [self.trial()], read=lambda prompt: next(replies), write=lambda v: None,
                               journal=self.rows.append, log_test=self.logger, clock=lambda: harness.now,
                               sleep=harness.sleep, timeout=.3, interval=.1, **kwargs)

        def test_physical_success_and_exact_ledger_call(self):
            result = self.execute_one(Harness())
            self.assertTrue(result[0]["success"])
            self.logger.assert_called_once_with(item="surgical_1", setting="surgical", lighting="normal", success=True, seconds=2.5, retries=0)
            self.assertTrue(self.rows[0]["physical_confirmed"])

        def test_operator_failure_counts_as_failure(self):
            self.assertFalse(self.execute_one(Harness(), ("", "f"))[0]["success"])
            self.assertFalse(self.logger.call_args.kwargs["success"])

        def test_successful_retry_counts_and_records_retry(self):
            result = self.execute_one(Harness(scenario="retry"))
            self.assertTrue(result[0]["success"])
            self.assertEqual(result[0]["retries"], 1)

        def test_fallback_set_down_is_not_nonsharp_handoff(self):
            self.assertFalse(self.execute_one(Harness(scenario="fallback"), ("",))[0]["success"])

        def test_practice_never_logs_measured_trials(self):
            result = self.execute_one(Harness(practice=True), (), practice=True, automatic=True)
            self.assertTrue(result[0]["success"])
            self.logger.assert_not_called()
            self.assertTrue(self.rows[0]["practice"])

        def test_fake_refused_before_commands(self):
            harness = Harness(practice=True)
            with self.assertRaises(TrialAbort):
                self.execute_one(harness)
            self.assertFalse(any(path == "/command" for _, path in harness.calls))

        def test_practice_refuses_real_controller(self):
            harness = Harness(practice=False)
            with self.assertRaises(TrialAbort):
                self.execute_one(harness, (), practice=True, automatic=True)
            self.assertFalse(any(path == "/command" for _, path in harness.calls))

        def test_malformed_events_stop_after_submission(self):
            class Malformed(Harness):
                def request(self, req):
                    if req.url.path == "/events/recent":
                        return httpx.Response(200, json={"unexpected": "object"})
                    return super().request(req)

            harness = Malformed()
            result = self.execute_one(harness, ("",))
            self.assertTrue(result[0]["aborted"])
            self.assertIn(("POST", "/stop"), harness.calls)
            self.logger.assert_called_once()

        def test_idle_before_the_first_step_is_not_completion(self):
            class Race(Harness):
                """/state reads idle once after the job is taken, before its first step event."""
                polls = 0

                def request(self, req):
                    if self.cid and req.url.path == "/state":
                        self.polls += 1
                        return httpx.Response(200, json={"step": "finding" if self.polls == 2 else "idle",
                                                         "queue": [], "setting": self.setting, "fake_arm": False})
                    if self.cid and req.url.path == "/events/recent":
                        kinds = [[], ["step"]][self.polls] if self.polls < 2 else ["step", "handed", "released"]
                        return httpx.Response(200, json=[{"command_id": self.cid, "type": k, "t": n,
                                                          "request_to_hand_s": 2.5 if k == "handed" else None,
                                                          "retries": 0} for n, k in enumerate(kinds)])
                    return super().request(req)

            self.assertTrue(self.execute_one(Race())[0]["success"])

        def test_timeout_stops_and_logs_failure(self):
            harness = Harness(scenario="timeout")
            result = self.execute_one(harness, ("",))
            self.assertTrue(result[0]["aborted"])
            self.assertFalse(result[0]["success"])
            self.assertIn(("POST", "/stop"), harness.calls)
            self.logger.assert_called_once()

        def test_stopped_never_rearms(self):
            harness = Harness(scenario="stopped")
            result = self.execute_one(harness, ("",))
            self.assertTrue(result[0]["aborted"])
            self.assertFalse(any(path == "/reset" for _, path in harness.calls))

        def test_rejection_is_logged_once(self):
            self.assertFalse(self.execute_one(Harness(scenario="rejected"), ("",))[0]["success"])
            self.logger.assert_called_once()

        def test_quit_before_command_is_not_an_attempt(self):
            harness = Harness()
            self.assertEqual(self.execute_one(harness, ("q",)), [])
            self.logger.assert_not_called()
            self.assertFalse(any(path == "/command" for _, path in harness.calls))

        def test_sharp_and_return_outcomes(self):
            sharp = self.trial(sharp=True)
            self.assertTrue(summarize(sharp, [{"type": "set_down"}], True)[0])
            returning = self.trial(action="return")
            ok, _, seconds = summarize(returning, [{"type": "returned", "request_to_hand_s": 99}], True)
            self.assertTrue(ok)
            self.assertIsNone(seconds)

        def test_real_no_prompt_mode_is_refused(self):
            with self.assertRaises(ValueError):
                self.execute_one(Harness(), (), automatic=True)

        def test_network_uncertainty_stops_and_logs_once(self):
            class Uncertain(Harness):
                def request(self, req):
                    if req.url.path == "/command":
                        raise httpx.ReadTimeout("offline injected uncertainty")
                    return super().request(req)

            harness = Uncertain()
            result = self.execute_one(harness, ("",))
            self.assertTrue(result[0]["aborted"])
            self.assertIn(("POST", "/stop"), harness.calls)
            self.logger.assert_called_once()

        def test_bench_adoption_is_separate_from_instrument_ledger_trials(self):
            harness, rows, logger = Harness(), [], Mock()
            replies = iter(["", "s"])
            with harness.client() as client:
                execute(client, [self.trial(setting="bench", item="bench_1")],
                        read=lambda prompt: next(replies), write=lambda value: None,
                        journal=rows.append, log_test=logger, bench_start=time.time() - 120)
            logger.assert_called_once()
            self.assertEqual(rows[1]["type"], "bench_adoption")
            self.assertAlmostEqual(rows[1]["minutes_since_first_demo"], 2, places=2)

        def test_actual_fake_controller_api_end_to_end(self):
            from unittest.mock import patch
            from fastapi.testclient import TestClient
            from .core import Controller
            from .fake_arm import FakeArm
            from .server import make_app

            arm = FakeArm(motion_s=.01, auto_pull_s=.01)
            arm.connect()
            logger, rows = Mock(), []
            with patch("controller.core.ledger", None):
                ctl = Controller(arm, fake_arm=True)
                try:
                    with TestClient(make_app(ctl)) as client:
                        result = execute(client, [self.trial(item="hemostat"), self.trial(item="hemostat", attempt=2)],
                                         practice=True, automatic=True, write=lambda value: None,
                                         journal=rows.append, log_test=logger, timeout=5, interval=.01)
                    self.assertEqual([r["success"] for r in result], [True, True])
                    self.assertEqual(ctl.state()["step"], "idle")
                    self.assertTrue(rows[0]["practice"])
                    logger.assert_not_called()
                finally:
                    arm.disconnect()
                    ctl._ledger_pool.shutdown(wait=True)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
