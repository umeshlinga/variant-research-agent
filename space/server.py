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
# Evidence Universe + Scatter Landscape payloads (v6).
# Aggregations only, computed once from the bundled tables and cached:
# the universe groups the real test-set rows by gene; the scatter is a
# decimation of the recorded GBM+R run's own rows (that table carries
# am_score, revel_score and the calibrated probability per variant).
# ---------------------------------------------------------------------------

_UNIVERSE: dict = {}
_SCATTER: dict = {}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def universe() -> dict:
    if _UNIVERSE:
        return _UNIVERSE
    rows = _data.test_rows()
    scored = _data.gbm_predictions()
    counts: dict[str, int] = {}
    by_gene: dict[str, list[int]] = {}
    for r in rows:
        gene = r.get("gene")
        try:
            aid = int(r.get("allele_id"))
        except (TypeError, ValueError):
            continue
        if not gene:
            continue
        counts[gene] = counts.get(gene, 0) + 1
        by_gene.setdefault(gene, []).append(aid)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    genes = []
    for gene, cnt in top:
        aids = sorted(by_gene[gene])
        n = len(aids)
        k = min(12, n)
        if k == 1:
            idx = [0]
        else:
            idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
        nodes = [{"allele_id": aids[i], "scored": aids[i] in scored}
                 for i in idx]
        genes.append({
            "gene": gene,
            "count": cnt,
            "scored_count": sum(1 for a in aids if a in scored),
            "nodes": nodes,
        })
    payload = {
        "total_variants": len(rows),
        "total_genes": len(counts),
        "scored_total": len(scored),
        "top_genes_sum": sum(c for _, c in top),
        "nodes_shown": len(genes) + sum(len(g["nodes"]) for g in genes),
        "genes": genes,
    }
    _UNIVERSE.update(payload)
    return payload


def scatter() -> dict:
    if _SCATTER:
        return _SCATTER
    path = _data.home / "data/processed_v2/test_predictions_trees.csv"
    base = []
    if path.exists():
        import csv as _csv
        with open(path, newline="") as fh:
            for raw in _csv.DictReader(fh):
                am = _f(raw.get("am_score"))
                rev = _f(raw.get("revel_score"))
                prob = _f(raw.get("prob_gbm_isotonic"))
                if am is None or rev is None or prob is None:
                    continue
                base.append((int(raw["allele_id"]), am, rev, prob))
    base.sort()
    pts = base[::5]
    payload = {
        "base_n": len(base),
        "plotted_n": len(pts),
        "rule": "every 5th variant in allele-id order",
        "points": [[round(am, 4), round(rev, 4), round(prob, 4)]
                   for _, am, rev, prob in pts],
    }
    _SCATTER.update(payload)
    return payload


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


@app.get("/api/universe")
def universe_route() -> dict:
    return universe()


@app.get("/api/scatter")
def scatter_route() -> dict:
    return scatter()


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
