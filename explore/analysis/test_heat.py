"""Offline tests for the heat report with synthetic thermal rows."""

from explore.analysis import heat


def sample(t, phase, temp, session="s1", motor="shoulder_lift"):
    return {"kind": "sample", "t": t, "phase": phase, "session": session, "motors": {motor: {"temp": temp}}}


def synthetic():
    rows = []
    for i in range(0, 121, 2):                       # idle at 46 C for 2 min
        rows.append(sample(1000 + i, "parked", 46))
    for i in range(0, 121, 2):                       # moving at 48 C
        rows.append(sample(2000 + i, "recording", 48))
    for i in range(0, 301, 10):                      # holding: +1 C/min exactly, from 50 C
        rows.append({"kind": "experiment", "t": 3000 + i, "phase": "torque_on_hold", "session": "s2",
                     "temps": {"shoulder_lift": 50 + i / 60}})
    for i in range(0, 301, 5):                       # cooling after: -0.5 C/min from 55 C
        rows.append(sample(4000 + i, "parked", 55 - 0.5 * i / 60, session="s3"))
    return rows


def test_phase_grouping():
    assert heat.group_of("parked") == "idle" and heat.group_of("off") == "idle"
    assert heat.group_of("recording") == heat.group_of("teleop") == heat.group_of("resetting") == "moving"
    assert heat.group_of("torque_on_hold") == "holding" and heat.group_of(None) is None


def test_motor_stats_rates():
    pts = heat.points(synthetic())
    m = heat.motor_stats(pts, "shoulder_lift")
    assert m["idle_c"] is not None and m["moving_c"] == 48
    assert abs(m["rise_c_per_min_holding"] - 1.0) < 0.01
    assert abs(m["cool_c_per_min"] - 0.5) < 0.01
    assert m["max_c"] == 55


def test_time_to_limit():
    assert heat.time_to_limit_s(50, 1.0, 60) == 600
    assert heat.time_to_limit_s(61, 1.0, 60) == 0
    assert heat.time_to_limit_s(50, 0.0, 60) is None and heat.time_to_limit_s(None, 1, 60) is None


def test_build(tmp_path):
    r = heat.build({"thermal": synthetic() + [{"kind": "event", "event": "joint_hold", "hot": True, "t": 5}]}, tmp_path)
    s = r["summary"]
    assert s["guard_c"] == 60 and s["limit_c"] == 70 and s["hot_events"] == 1
    assert s["motors"][0]["motor"] == "shoulder_lift" and s["motors"][0]["time_to_limit_s"] is not None
    assert len(s["series"]["t_min"]) <= 400
    assert {n["name"] for n in r["numbers"]} >= {"Thermal samples"}
    assert (tmp_path / "heat_cooling.png").exists()


def test_empty(tmp_path):
    r = heat.build({"thermal": []}, tmp_path)
    assert r["summary"]["motors"] == [] and r["numbers"][0]["value"] == "no real data yet"
