"""Q-GreenFleet REST API (FastAPI).

Run: ``make api`` (http://localhost:8000, interactive docs at /docs).

Environment (all optional; render.yaml sets them for the free hosted demo):
    GREENFLEET_WORKERS     background job threads (default 2)
    GREENFLEET_MAX_BUDGET  cap on optimizer evaluations per request (default: no cap beyond validation)
    GREENFLEET_WARMUP=1    on start-up, precompute the default scenario's runs so the first visitor gets
                           them instantly (identical requests are served from the finished job)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from greenfleet import __version__
from greenfleet.api import report as report_mod
from greenfleet.api import service as S
from greenfleet.api.jobs import JobManager
from greenfleet.scenarios.scenario import OBJECTIVES, Scenario

log = logging.getLogger("greenfleet.api")
WORKERS = int(os.environ.get("GREENFLEET_WORKERS", "2"))
MAX_BUDGET = int(os.environ.get("GREENFLEET_MAX_BUDGET", "200000"))
WARMUP = os.environ.get("GREENFLEET_WARMUP", "0") == "1"
MAX_BODY_BYTES = 2_000_000
DEFAULT_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
jobs = JobManager(workers=WORKERS)


def jsonable(x):
    """numpy scalars/arrays to Python; NaN/inf (e.g. the CII ratio of an infeasible plan) to null."""
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, (np.integer, np.bool_)):
        return x.item()
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(x) else None
    return x


def _job_key(kind: str, sc: Scenario, **params) -> str:
    return json.dumps({"kind": kind, "scenario": sc.to_dict(), **params}, sort_keys=True, default=str)


def submit_optimize(sc: Scenario, algorithm: str, budget: int, seed: int, pinned: bool = False):
    budget = min(budget, MAX_BUDGET)
    return jobs.submit("optimize", lambda j: S.run_optimization(j, sc, algorithm, budget, seed),
                       key=_job_key("optimize", sc, algorithm=algorithm, budget=budget, seed=seed), pinned=pinned)


def submit_timeline(sc: Scenario, years: list[int], budget: int, preference: str, pinned: bool = False):
    budget = min(budget, MAX_BUDGET)
    return jobs.submit("timeline", lambda j: S.run_timeline(j, sc, years, budget, preference),
                       key=_job_key("timeline", sc, years=years, budget=budget, preference=preference), pinned=pinned)


def submit_qubo(sc: Scenario, weights: dict, solver: str, pinned: bool = False):
    return jobs.submit("qubo", lambda j: S.run_qubo(j, sc, weights, solver),
                       key=_job_key("qubo", sc, weights=weights, solver=solver), pinned=pinned)


def submit_qaoa(sc: Scenario, weights: dict, services: int, options: int, layers: int, pinned: bool = False):
    return jobs.submit("qaoa", lambda j: S.run_qaoa(j, sc, weights, services, options, layers),
                       key=_job_key("qaoa", sc, weights=weights, services=services, options=options, layers=layers),
                       pinned=pinned)


def default_scenario() -> Scenario:
    """The scenario the dashboard opens with (see frontend/src/lib/store.tsx)."""
    return Scenario.from_dict({**Scenario().to_dict(), "network": "india", "year": 2030})


def warm_up() -> None:
    """Precompute what a first visitor clicks: network, optimizer run, 2025-2050 pathway, MACC, QUBO."""
    sc = default_scenario()
    try:
        S.model_card()
        S.network(sc)
        submit_optimize(sc, "QMOEA-H", 6000, 0, pinned=True)
        submit_timeline(sc, DEFAULT_YEARS, 3000, "cost", pinned=True)
        S.macc(sc)
        submit_qaoa(sc, {"emissions": 0.5, "cost": 0.5}, 4, 3, 3, pinned=True)
        submit_qubo(sc, {"emissions": 0.5, "cost": 0.5}, "pi_sqa", pinned=True)
        log.info("warm-up submitted")
    except Exception:  # warm-up is best effort; the endpoints still compute on demand
        log.exception("warm-up failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if WARMUP:
        threading.Thread(target=warm_up, name="warm-up", daemon=True).start()
    yield


app = FastAPI(title="Q-GreenFleet API", version=__version__, lifespan=lifespan,
              description="Quantum-inspired fuel prediction and green fleet optimization (SIH 2026, PS 26138).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def limit_body(request: Request, call_next):
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)
    return await call_next(request)


# ------------------------------------------------------------------ request models
class ScenarioIn(BaseModel):
    scenario: dict = Field(default_factory=dict, description="Scenario fields (see /api/meta default_scenario)")

    def build(self) -> Scenario:
        try:
            return Scenario.from_dict(self.scenario)
        except TypeError as exc:
            raise HTTPException(422, f"invalid scenario: {exc}") from exc


class OptimizeIn(ScenarioIn):
    algorithm: str = "QMOEA-H"
    budget: int = Field(6000, ge=200, le=200000)
    seed: int = 0


class GenesIn(ScenarioIn):
    genes: dict | None = None
    plan: list[dict] | None = None

    def to_genes(self, sc: Scenario):
        if self.genes:
            return S.genes_from_json(self.genes)
        if self.plan:
            return S.plan_to_genes(sc, self.plan)
        return S.get_problem(sc).baseline_genes("current_practice")


class RobustIn(GenesIn):
    samples: int = Field(400, ge=50, le=5000)


class TimelineIn(ScenarioIn):
    years: list[int] = Field(default_factory=lambda: list(DEFAULT_YEARS), min_length=1, max_length=12)
    budget: int = Field(4000, ge=500, le=50000)
    preference: str = "cost"


class ExactIn(ScenarioIn):
    objective: str = "cost"


class QuboIn(ScenarioIn):
    weights: dict[str, float] = {"fuel": 1 / 3, "emissions": 1 / 3, "cost": 1 / 3}
    solver: str = "pi_sqa"


class QaoaIn(ScenarioIn):
    weights: dict[str, float] = {"emissions": 0.5, "cost": 0.5}
    services: int = Field(4, ge=2, le=5)
    options: int = Field(3, ge=2, le=3)
    layers: int = Field(3, ge=1, le=4)


class PredictIn(BaseModel):
    vessel_class: str = "PANAMAX_C"
    speed_kn: float = 16.0
    load_ratio: float = Field(0.85, ge=0, le=1)
    wind_speed_ms: float = Field(6.0, ge=0, le=40)
    wind_rel_deg: float = Field(45.0, ge=0, le=180)
    wave_height_m: float = Field(1.5, ge=0, le=15)
    wave_rel_deg: float = Field(45.0, ge=0, le=180)
    days_since_cleaning: float = Field(365.0, ge=0, le=2000)
    fuel: str = "VLSFO"
    ship_id: str | None = None


class ReportIn(GenesIn):
    include_macc: bool = True
    include_robustness: bool = True
    algorithm: str | None = None


class CsvIn(BaseModel):
    csv: str = Field(max_length=500_000)


def _guard(fn, *args):
    try:
        return fn(*args)
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(422, f"{exc.__class__.__name__}: {exc}") from exc


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "model": S.model_card().get("available", False),
            "jobs_pending": jobs.pending()}


@app.get("/api/meta")
def get_meta():
    return S.meta()


@app.post("/api/network")
def post_network(body: ScenarioIn):
    return _guard(S.network, body.build())


@app.post("/api/predict")
def post_predict(body: PredictIn):
    return _guard(S.predict, body.model_dump())


@app.get("/api/model")
def get_model():
    return S.model_card()


@app.post("/api/optimize")
def post_optimize(body: OptimizeIn):
    sc = body.build()
    if body.algorithm not in S.ALGORITHMS:
        raise HTTPException(422, f"unknown algorithm {body.algorithm}; choose from {list(S.ALGORITHMS)}")
    job, reused = submit_optimize(sc, body.algorithm, body.budget, body.seed)
    return {**job.summary(), "reused": reused}


@app.post("/api/timeline")
def post_timeline(body: TimelineIn):
    sc = body.build()
    if any(not 2020 <= y <= 2060 for y in body.years):
        raise HTTPException(422, "years must lie between 2020 and 2060")
    if body.preference not in (*OBJECTIVES, "balanced"):
        raise HTTPException(422, f"preference must be one of {[*OBJECTIVES, 'balanced']}")
    job, reused = submit_timeline(sc, body.years, body.budget, body.preference)
    return {**job.summary(), "reused": reused}


@app.post("/api/qubo")
def post_qubo(body: QuboIn):
    sc = body.build()
    if body.solver not in ("pi_sqa", "openjij_sqa", "openjij_sa"):
        raise HTTPException(422, "solver must be pi_sqa, openjij_sqa or openjij_sa")
    job, reused = submit_qubo(sc, body.weights, body.solver)
    return {**job.summary(), "reused": reused}


@app.post("/api/qaoa")
def post_qaoa(body: QaoaIn):
    """Gate-model QAOA on a small fleet sub-problem (exact state-vector simulation, OpenQASM 2.0 export)."""
    sc = body.build()
    if body.services * body.options > 16:
        raise HTTPException(422, "at most 16 qubits (services x options)")
    job, reused = submit_qaoa(sc, body.weights, body.services, body.options, body.layers)
    return {**job.summary(), "reused": reused}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    out = job.summary()
    if job.status == "done":
        out["result"] = jsonable(job.result)
    return out


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    # a finished job (a repeat of an earlier request) is replayed at a readable pace, so the Pareto front
    # still visibly builds up instead of jumping straight to the end
    replay = job.status in ("done", "error")

    async def gen():
        sent = 0
        while True:
            while sent < len(job.events):
                ev = job.events[sent]
                sent += 1
                yield f"data: {json.dumps(jsonable(ev), allow_nan=False)}\n\n"
                if ev.get("type") in ("done", "error"):
                    return
                if replay and ev.get("type") == "progress":
                    await asyncio.sleep(0.05)
            if job.status in ("done", "error") and sent >= len(job.events):
                return
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/evaluate")
def post_evaluate(body: GenesIn):
    sc = body.build()
    return _guard(lambda: S.evaluate(sc, body.to_genes(sc)))


@app.post("/api/robustness")
def post_robustness(body: RobustIn):
    sc = body.build()
    return _guard(lambda: S.robustness(sc, body.to_genes(sc), body.samples))


@app.post("/api/macc")
def post_macc(body: ScenarioIn):
    return _guard(S.macc, body.build())


@app.post("/api/exact")
def post_exact(body: ExactIn):
    if body.objective not in ("fuel", "emissions", "cost"):
        raise HTTPException(422, "objective must be fuel, emissions or cost")
    return _guard(S.run_exact, body.build(), body.objective)


@app.post("/api/report", response_class=HTMLResponse)
def post_report(body: ReportIn):
    sc = body.build()
    genes = body.to_genes(sc)
    ev = S.evaluate(sc, genes)
    problem = S.get_problem(sc)
    html = report_mod.render(
        ev, sc.to_dict(), ev.get("explanation"),
        macc=S.macc(sc) if body.include_macc else None,
        robustness=S.robustness(sc, genes, 300) if body.include_robustness else None,
        algorithm=body.algorithm, network_name=problem.rs.name,
    )
    return HTMLResponse(html, headers={"Content-Disposition": 'inline; filename="qgreenfleet_report.html"'})


@app.get("/api/benchmarks")
def get_benchmarks():
    return S.benchmarks()


@app.post("/api/routes/parse")
def post_routes_csv(body: CsvIn):
    return {"routes": _guard(S.parse_routes_csv, body.csv)}


@app.get("/api/routes/example.csv", response_class=PlainTextResponse)
def get_example_csv():
    return PlainTextResponse(S.example_routes_csv(), media_type="text/csv")


# ------------------------------------------------------------------ single-page app (production build)
_dist = S.static_dir()
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (_dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(_dist.resolve()):
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
