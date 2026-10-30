"""FastAPI server for the Variant Research Agent Space (Docker SDK).

Serves a fully hand-built frontend (static/index.html) and a JSON API
wrapping the unchanged pipeline:

  GET  /              -> the custom web app
  GET  /api/health    -> {"status": "ok"}
  POST /api/research  -> {"variant": "..."} runs the full pipeline in a
                         threadpool and returns the structured run state
                         plus real test-set distribution histograms
                         computed server-side from the bundled tables.

Default mode is OFFLINE (deterministic, local data only, no LLM, no
network gatherers), matching the published benchmark configuration.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

# Offline by default: deterministic, reproducible, no endpoint probing.
os.environ.setdefault("VRA_OFFLINE", "1")

# Layout: server.py at repo root; package under src/.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# Bundled data: vus_data/ mirrors the vus-evidence-agent data/ layout.
_BUNDLED = _ROOT / "vus_data"
if _BUNDLED.is_dir():
    os.environ.setdefault("VRA_VUS_HOME", str(_BUNDLED))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from variant_research_agent import dossier as dossier_mod  # noqa: E402
from variant_research_agent.data import LocalData  # noqa: E402
from variant_research_agent.graph import run  # noqa: E402

app = FastAPI(title="Variant Research Agent")
_STATIC = _ROOT / "static"

# ---------------------------------------------------------------------------
# Real reference distributions from the bundled test-set tables.
# Computed once from the actual local columns (the same columns the
# pipeline's own percentile analyses use) and cached: the bundled
# tables are static for the life of the process.
# ---------------------------------------------------------------------------

_data = LocalData()
_VALUES: dict[str, list[float]] = {}
_DIST: dict[str, dict] = {}


def _hist(values: list[float], lo: float, hi: float, bins: int = 20):
    counts = [0] * bins
    step = (hi - lo) / bins
    for v in values:
        i = int((v - lo) / step)
        if i < 0:
            i = 0
        elif i >= bins:
            i = bins - 1
        counts[i] += 1
    edges = [lo + step * i for i in range(bins + 1)]
    return counts, edges


def _column(name: str) -> list[float]:
    if name not in _VALUES:
        _VALUES[name] = [float(v) for v in _data.column_distribution(name)
                         if v is not None]
    return _VALUES[name]


def _percentile(values: list[float], x: float) -> float:
    if not values:
        return 0.0
    below = sum(1 for v in values if v <= x)
    return round(100.0 * below / len(values), 1)


def distributions() -> dict:
    """Histogram payload for the three reference distributions.

    AM and REVEL are binned on [0, 1]; gnomAD AF is binned on a log10
    scale over the positive recorded frequencies. Every bin count is a
    count of real rows in the bundled temporal test set."""
    if _DIST:
        return _DIST
    out: dict[str, dict] = {}
    for key, col in (("am", "am_score"), ("revel", "revel_score")):
        vals = _column(col)
        counts, edges = _hist(vals, 0.0, 1.0)
        out[key] = {"bins": counts, "edges": edges, "n": len(vals),
                    "scale": "linear"}
    afs = [v for v in _column("gnomad_af") if v > 0]
    if afs:
        logs = [math.log10(v) for v in afs]
        lo, hi = math.floor(min(logs)), math.ceil(max(logs))
        if hi <= lo:
            hi = lo + 1
        counts, edges = _hist(logs, float(lo), float(hi))
        out["af"] = {"bins": counts, "edges": edges, "n": len(afs),
                     "scale": "log10"}
    _DIST.update(out)
    return out


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    variant: str


_STATE_KEYS = ("query", "record", "plan", "plan_mode", "evidence",
               "analyses", "judgment", "gate", "review", "design",
               "narrative", "notes", "events")


def _research_sync(variant: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        state = run(variant, out_dir=tmp, live=False)
        md = dossier_mod.render_dossier(state)
    payload = {k: state.get(k) for k in _STATE_KEYS}
    payload["dossier_markdown"] = md
    payload["ok"] = True

    rec = state.get("record") or {}
    # This variant's own gene prior from the recorded GBM+R run
    # (real value from test_predictions_trees.csv; None when the
    # variant was never scored by that run).
    gene_prior = None
    try:
        row = _data.gbm_predictions().get(int(rec.get("allele_id"))) or {}
        gene_prior = row.get("gene_prior")
    except Exception:
        gene_prior = None
    payload["gene_prior"] = gene_prior

    # Distribution graphs, personalised: this variant's value and its
    # percentile inside each real reference distribution.
    dists = {}
    raw = distributions()
    values = {"am": rec.get("am_score"), "revel": rec.get("revel_score"),
              "af": rec.get("gnomad_af_recorded")}
    cols = {"am": "am_score", "revel": "revel_score", "af": "gnomad_af"}
    for key, d in raw.items():
        entry = dict(d)
        v = values.get(key)
        entry["value"] = v
        if v is not None:
            vals = _column(cols[key])
            if key == "af":
                vals = [x for x in vals if x > 0]
            entry["percentile"] = _percentile(vals, float(v))
        else:
            entry["percentile"] = None
        dists[key] = entry
    payload["distributions"] = dists
    return payload


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/research")
async def research(req: ResearchRequest):
    variant = (req.variant or "").strip()
    if not variant:
        return JSONResponse({"ok": False, "error": "Enter a variant first."},
                            status_code=400)
    try:
        payload = await run_in_threadpool(_research_sync, variant)
    except ValueError as e:
        return {"ok": False, "unresolvable": True, "variant": variant,
                "error": str(e)}
    return payload


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
