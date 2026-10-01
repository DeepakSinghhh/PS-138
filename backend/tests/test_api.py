import json
import time

import pytest
from fastapi.testclient import TestClient

from greenfleet.api.main import app

client = TestClient(app)


def _wait(job_id, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}").json()
        if r["status"] in ("done", "error"):
            return r
        time.sleep(0.3)
    raise TimeoutError(job_id)


def test_health_and_meta():
    assert client.get("/api/health").json()["status"] == "ok"
    m = client.get("/api/meta").json()
    assert {"fuels", "vessel_classes", "ports", "networks", "algorithms", "regulations"} <= set(m)
    assert "QMOEA-H" in m["algorithms"]


def test_network_and_baselines():
    r = client.post("/api/network", json={"scenario": {"network": "india", "year": 2030}}).json()
    assert len(r["routes"]) == 12 and "current_practice" in r["baselines"]
    assert all(len(rt["geometry"]) >= 2 for rt in r["routes"])


def test_predict_returns_curve_and_alt_fuel():
    r = client.post("/api/predict", json={"vessel_class": "SUPRAMAX", "speed_kn": 12, "fuel": "AMMONIA_E"}).json()
    assert r["fuel_hfo_eq_tpd"] > 0 and r["interval_tpd"][0] <= r["fuel_hfo_eq_tpd"] <= r["interval_tpd"][1]
    assert "AMMONIA_E" in r["fuel_mass_tpd"] and len(r["curve"]["speed_kn"]) == 25
    bad = client.post("/api/predict", json={"vessel_class": "NOPE"})
    assert bad.status_code == 422


def test_optimize_job_streams_and_returns_front():
    j = client.post("/api/optimize", json={"scenario": {"network": "india", "year": 2030}, "budget": 1500}).json()
    with client.stream("GET", f"/api/jobs/{j['id']}/stream") as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    assert any(e["type"] == "progress" for e in events) and events[-1]["type"] == "done"
    res = _wait(j["id"])["result"]
    assert res["solutions"] and res["picks"]["balanced"] < len(res["solutions"])
    assert "summary" in res["explanation"]
    genes = res["solutions"][0]["genes"]
    ev = client.post("/api/evaluate", json={"scenario": {"network": "india", "year": 2030}, "genes": genes}).json()
    assert len(ev["routes"]) == 12
    rep = client.post("/api/report", json={"scenario": {"network": "india", "year": 2030}, "genes": genes,
                                           "include_robustness": False})
    assert rep.status_code == 200 and "Fleet allocation" in rep.text


def test_optimize_with_exact_warm_start():
    j = client.post("/api/optimize", json={"scenario": {"network": "india", "year": 2030}, "budget": 800,
                                           "algorithm": "QMOEA-H+MILP"}).json()
    res = _wait(j["id"])["result"]
    assert res["feasible"] and "hybrid" in res["algorithm"]


def test_plan_evaluation_by_readable_plan_and_robustness():
    body = {"scenario": {"network": "india", "year": 2030},
            "plan": [{"route_id": "R09", "fuel": "LNG_HP", "extra_ships": 2, "speed_u": 0.0, "shore_power": True}]}
    ev = client.post("/api/evaluate", json=body).json()
    r09 = next(r for r in ev["routes"] if r["route_id"] == "R09")
    assert r09["fuel"] == "LNG_HP" and r09["shore_power"]
    rb = client.post("/api/robustness", json={**body, "samples": 100}).json()
    assert rb["cost"]["p5"] <= rb["cost"]["mean"] <= rb["cost"]["p95"]


def test_macc_and_exact():
    m = client.post("/api/macc", json={"scenario": {"network": "india", "year": 2030}}).json()
    assert m["measures"]
    ex = client.post("/api/exact", json={"scenario": {"network": "india", "year": 2030}, "objective": "emissions"}).json()
    assert ex["status"] == "Optimal" and ex["feasible"]


@pytest.mark.slow
def test_qubo_and_timeline_jobs():
    q = client.post("/api/qubo", json={"scenario": {"network": "india", "year": 2030}, "solver": "openjij_sa"}).json()
    res = _wait(q["id"])
    assert res["status"] == "done" and res["result"]["gap_pct_vs_exact"] < 50
    t = client.post("/api/timeline", json={"scenario": {"network": "india"}, "years": [2025, 2040], "budget": 800}).json()
    assert len(_wait(t["id"])["result"]["rows"]) == 2


def test_routes_csv_roundtrip():
    csv = client.get("/api/routes/example.csv").text
    routes = client.post("/api/routes/parse", json={"csv": csv}).json()["routes"]
    assert len(routes) == 4
    net = client.post("/api/network", json={"scenario": {"custom_routes": routes, "year": 2030}}).json()
    assert len(net["routes"]) == 4
    assert client.post("/api/routes/parse", json={"csv": "a,b\n1,2\n"}).status_code == 422


def test_identical_requests_share_one_job_and_replay():
    body = {"scenario": {"network": "eu", "year": 2035}, "budget": 800, "seed": 3}
    a = client.post("/api/optimize", json=body).json()
    b = client.post("/api/optimize", json=body).json()
    assert a["reused"] is False and b["reused"] is True and a["id"] == b["id"]
    _wait(a["id"])
    # a finished job replays its events on a late stream
    with client.stream("GET", f"/api/jobs/{a['id']}/stream") as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done" and any(e["type"] == "progress" for e in events)
    other = client.post("/api/optimize", json={**body, "seed": 4}).json()
    assert other["id"] != a["id"]


def test_request_limits_and_static_guard():
    too_big = client.post("/api/routes/parse", content=b"{" + b" " * 2_100_000 + b"}",
                          headers={"content-type": "application/json"})
    assert too_big.status_code == 413
    bad_years = client.post("/api/timeline", json={"scenario": {}, "years": [1990]})
    assert bad_years.status_code == 422
    assert client.post("/api/timeline", json={"scenario": {}, "preference": "nope"}).status_code == 422
    r = client.get("/..%2f..%2fpyproject.toml")
    assert "[project]" not in r.text


def test_job_manager_reuse_and_eviction():
    from greenfleet.api.jobs import JobManager

    jm = JobManager(workers=1, keep=2)
    pinned, _ = jm.submit("x", lambda j: 1, key="p", pinned=True)
    for i in range(4):
        job, reused = jm.submit("x", lambda j, i=i: i, key=f"k{i}")
        assert not reused
        while job.status != "done":
            time.sleep(0.01)
    assert jm.get(pinned.id) is not None            # pinned warm-up jobs survive eviction
    assert jm.submit("x", lambda j: 2, key="p")[1] is True
    failing, _ = jm.submit("x", lambda j: 1 / 0, key="f")
    while failing.status != "error":
        time.sleep(0.01)
    assert jm.submit("x", lambda j: 1, key="f")[1] is False   # a failed job is retried, not reused


def test_qaoa_job():
    j = client.post("/api/qaoa", json={"scenario": {"network": "india", "year": 2030}, "services": 2, "options": 3,
                                        "layers": 1}).json()
    res = _wait(j["id"])["result"]
    assert res["qubits"] == 6 and res["top_plans"] and res["qasm"].startswith("OPENQASM 2.0;")
    assert client.post("/api/qaoa", json={"scenario": {}, "services": 9}).status_code == 422


def test_report_in_rupees():
    base = {"scenario": {"network": "india", "year": 2030}, "include_robustness": False}
    inr = client.post("/api/report", json={**base, "currency": "INR"})
    usd = client.post("/api/report", json=base)
    assert inr.status_code == 200 and "crore ₹" in inr.text and "₹" in inr.text
    assert "M USD" in usd.text and "crore" not in usd.text
    assert client.post("/api/report", json={**base, "currency": "GBP"}).status_code == 422
    assert client.get("/api/meta").json()["fx"]["usd_to_inr"] > 0
