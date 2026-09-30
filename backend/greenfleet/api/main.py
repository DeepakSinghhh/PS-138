"""Q-GreenFleet REST API (FastAPI).

Run: ``make api`` (http://localhost:8000, interactive docs at /docs).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from greenfleet import __version__
from greenfleet.api import report as report_mod
from greenfleet.api import service as S
from greenfleet.api.jobs import JobManager
from greenfleet.scenarios.scenario import Scenario

app = FastAPI(title="Q-GreenFleet API", version=__version__,
              description="Quantum-inspired fuel prediction and green fleet optimization (SIH 2026, PS 26138).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
jobs = JobManager(workers=2)


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
    years: list[int] = [2025, 2030, 2035, 2040, 2045, 2050]
    budget: int = Field(4000, ge=500, le=50000)
    preference: str = "cost"


class ExactIn(ScenarioIn):
    objective: str = "cost"


class QuboIn(ScenarioIn):
    weights: dict[str, float] = {"fuel": 1 / 3, "emissions": 1 / 3, "cost": 1 / 3}
    solver: str = "pi_sqa"


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
    csv: str


def _guard(fn, *args):
    try:
        return fn(*args)
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(422, f"{exc.__class__.__name__}: {exc}") from exc


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "model": S.model_card().get("available", False)}


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
    job = jobs.submit("optimize", lambda j: S.run_optimization(j, sc, body.algorithm, body.budget, body.seed))
    return job.summary()


@app.post("/api/timeline")
def post_timeline(body: TimelineIn):
    sc = body.build()
    job = jobs.submit("timeline", lambda j: S.run_timeline(j, sc, body.years, body.budget, body.preference))
    return job.summary()


@app.post("/api/qubo")
def post_qubo(body: QuboIn):
    sc = body.build()
    if body.solver not in ("pi_sqa", "openjij_sqa", "openjij_sa"):
        raise HTTPException(422, "solver must be pi_sqa, openjij_sqa or openjij_sa")
    job = jobs.submit("qubo", lambda j: S.run_qubo(j, sc, body.weights, body.solver))
    return job.summary()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    out = job.summary()
    if job.status == "done":
        out["result"] = job.result
    return out


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    async def gen():
        sent = 0
        while True:
            while sent < len(job.events):
                ev = job.events[sent]
                sent += 1
                yield f"data: {json.dumps(ev, default=float)}\n\n"
                if ev.get("type") in ("done", "error"):
                    return
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
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
