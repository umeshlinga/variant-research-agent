"""Hugging Face Space app for the Variant Research Agent.

This is the source of the LIVE Space app
(https://evidra-variant-research-agent.hf.space). Wraps the CLI
pipeline for a single variant and renders a visual, card-based
research dossier from the pipeline's structured run state. Default
mode is OFFLINE (deterministic, local data only, no LLM, no network
gatherers), matching the benchmark configuration.

Layout differences in the deployed Space copy:
  * There this file sits at the Space repo root (app_file: app.py),
    so its sys.path shim points at <root>/src; here the shim points
    at the repo root (parents[1]) with the package under <root>/src.
  * The Space bundles the vus-evidence-agent processed test tables
    under vus_data/; this file defaults VRA_VUS_HOME to that bundled
    directory when the env var is unset and the directory exists.
    The tables are the source project's data — check its
    licence/terms before redistributing them inside a Space.
  * Live mode and LLM mode remain OFF. Enabling them is a deliberate
    deployment decision (secrets for LLM_API_KEY via Space secrets;
    never hardcode a key).

Presentation layer (Oct 2026 redesign): Google-style product page —
clean white surfaces, Omevra evidence green (#0b7a37) primary accent,
color-coded verdict hero, stat tiles, direction/severity chips,
percentile bars, reviewer and experiment-design cards. The pipeline
package is untouched; everything rendered here comes from the run
state dict returned by variant_research_agent.graph.run().
"""
from __future__ import annotations

import html
import os
import sys
import tempfile
from pathlib import Path

# Offline by default: deterministic, reproducible, no endpoint probing.
os.environ.setdefault("VRA_OFFLINE", "1")

# Space layout: app.py at repo root; package under src/.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

# Bundled data: vus_data/ mirrors the vus-evidence-agent data/ layout.
_BUNDLED = _REPO / "vus_data"
if _BUNDLED.is_dir():
    os.environ.setdefault("VRA_VUS_HOME", str(_BUNDLED))

import gradio as gr  # noqa: E402

from variant_research_agent import dossier as dossier_mod  # noqa: E402
from variant_research_agent.graph import run  # noqa: E402

GITHUB_URL = "https://github.com/umeshlinga/variant-research-agent"
BENCHMARK_URL = GITHUB_URL + "/blob/main/BENCHMARK_REPORT.md"

# ---------------------------------------------------------------------------
# Static page furniture
# ---------------------------------------------------------------------------

_LOGO_SVG = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'aria-hidden="true"><path d="M7 3c0 6 10 6 10 12" stroke="#fff" '
    'stroke-width="2.2" stroke-linecap="round"/><path d="M17 3c0 6-10 6-10 12" '
    'stroke="#fff" stroke-width="2.2" stroke-linecap="round" opacity=".65"/>'
    '<path d="M8.5 6.5h7M8.5 17.5h7" stroke="#fff" stroke-width="2.2" '
    'stroke-linecap="round"/></svg>')

HEADER_HTML = f"""
<div class="vra-topbar">
  <div class="vra-brand">
    <div class="vra-logo">{_LOGO_SVG}</div>
    <div>
      <div class="vra-product">Variant Research Agent</div>
      <div class="vra-brand-sub">by Omevra</div>
    </div>
  </div>
  <nav class="vra-nav">
    <a href="{GITHUB_URL}" target="_blank" rel="noopener">GitHub</a>
    <a href="{BENCHMARK_URL}" target="_blank" rel="noopener">Benchmark</a>
    <span class="vra-badge-soft">Research only</span>
  </nav>
</div>
<div class="vra-hero-text">
  <h1>Variant in. <span class="vra-accent">Research dossier</span> out.</h1>
  <p>An autonomous agent that plans the investigation, gathers cited
  evidence, runs its own analyses in a sandbox, judges with a calibrated
  model, reviews its own verdict adversarially, and designs the
  experiment that would settle the variant — or declines, honestly,
  when the evidence is too thin.</p>
</div>
"""

STATS_HTML = """
<div class="vra-stats">
  <div class="vra-stat"><div class="vra-stat-num">300</div>
    <div class="vra-stat-label">variants benchmarked on a ClinVar temporal split</div></div>
  <div class="vra-stat"><div class="vra-stat-num">89.2%</div>
    <div class="vra-stat-label">accuracy on concluded cases (99 of 111)</div></div>
  <div class="vra-stat"><div class="vra-stat-num">100%</div>
    <div class="vra-stat-label">decline precision — 189 of 189 declines were protective</div></div>
  <div class="vra-stat"><div class="vra-stat-num">0.970</div>
    <div class="vra-stat-label">calibrated model AUROC on the temporal test set</div></div>
  <div class="vra-stat"><div class="vra-stat-num">48</div>
    <div class="vra-stat-label">automated tests passing</div></div>
</div>
<p class="vra-stats-note">Every number above is from the published
benchmark — see the <a href="{bench}" target="_blank" rel="noopener">benchmark report</a>.</p>
""".replace("{bench}", BENCHMARK_URL)

FOOTER_HTML = f"""
<div class="vra-footer">
  <p><strong>Research project only — not for clinical use.</strong>
  Evidence summaries are not clinical classifications.</p>
  <p>Temporal integrity: only prediction-time records (ClinVar frozen
  2024-01) are used as evidence; later reclassifications are never
  loaded. This demo runs in the offline benchmark configuration —
  deterministic local data, no LLM, no live gatherers.</p>
  <p><a href="{GITHUB_URL}" target="_blank" rel="noopener">Source on GitHub</a>
  · <a href="{BENCHMARK_URL}" target="_blank" rel="noopener">Benchmark report</a>
  · Built on the vus-evidence-agent temporal test set (27,748 variants).</p>
</div>
"""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Roboto+Mono:wght@400;500&display=swap');
:root{
  --green:#0b7a37; --green-dark:#0a5c2a; --green-tint:#e6f4ea;
  --red:#b91c1c; --red-dark:#a50e0e; --red-tint:#fce8e6;
  --amber:#b06000; --amber-tint:#fef7e0; --amber-border:#f9ab00;
  --ink:#1d1d1f; --grey:#5f6368; --faint:#80868b;
  --border:#dadce0; --card-border:#e0e3e7; --surface:#f8f9fa;
}
.gradio-container{ background:#ffffff !important; font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif !important; color:var(--ink); }
.vra-wrap{ max-width:1060px; margin:0 auto; padding:8px 4px 0; }
.vra-wrap *{ box-sizing:border-box; }
.vra-topbar{ display:flex; justify-content:space-between; align-items:center; padding:10px 2px 18px; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:10px; }
.vra-brand{ display:flex; align-items:center; gap:12px; }
.vra-logo{ width:44px; height:44px; border-radius:12px; background:linear-gradient(135deg,#0b7a37,#0a5c2a); display:flex; align-items:center; justify-content:center; box-shadow:0 2px 8px rgba(11,122,55,.28); }
.vra-product{ font-size:20px; font-weight:700; letter-spacing:-.01em; line-height:1.15; }
.vra-brand-sub{ font-size:12.5px; color:var(--grey); font-weight:500; }
.vra-nav{ display:flex; align-items:center; gap:18px; font-size:14px; font-weight:500; }
.vra-nav a{ color:var(--green-dark); text-decoration:none; }
.vra-nav a:hover{ text-decoration:underline; }
.vra-badge-soft{ background:var(--green-tint); color:var(--green-dark); border:1px solid #a3d9b1; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.vra-hero-text{ padding:30px 2px 6px; max-width:820px; }
.vra-hero-text h1{ font-size:40px; line-height:1.12; font-weight:800; letter-spacing:-.02em; margin:0 0 12px; }
.vra-accent{ color:var(--green); }
.vra-hero-text p{ font-size:16.5px; line-height:1.55; color:var(--grey); margin:0; }
.vra-stats{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:26px 0 6px; }
.vra-stat{ background:#fff; border:1px solid var(--card-border); border-radius:16px; padding:16px 14px; transition:box-shadow .18s ease, transform .18s ease; }
.vra-stat:hover{ box-shadow:0 6px 18px rgba(32,33,36,.10); transform:translateY(-1px); }
.vra-stat-num{ font-size:28px; font-weight:800; color:var(--green-dark); letter-spacing:-.01em; }
.vra-stat-label{ font-size:12.5px; color:var(--grey); line-height:1.45; margin-top:4px; }
.vra-stats-note{ font-size:12.5px; color:var(--faint); margin:6px 2px 0; }
.vra-stats-note a{ color:var(--green-dark); }
.vra-section-title{ font-size:19px; font-weight:700; margin:30px 0 4px; letter-spacing:-.01em; }
.vra-section-sub{ font-size:13.5px; color:var(--grey); margin:0 0 14px; line-height:1.5; }
.vra-input-label{ font-size:13px; font-weight:600; color:var(--grey); margin:26px 0 8px; text-transform:uppercase; letter-spacing:.06em; }
/* verdict hero */
.vra-hero{ border-radius:20px; padding:26px 28px; margin-top:22px; border:1px solid var(--card-border); background:#fff; box-shadow:0 4px 20px rgba(32,33,36,.07); }
.vra-hero-path{ border-top:6px solid var(--red); background:linear-gradient(180deg,#fdf4f3,#ffffff 55%); }
.vra-hero-ben{ border-top:6px solid var(--green); background:linear-gradient(180deg,#f0f8f2,#ffffff 55%); }
.vra-hero-dec{ border-top:6px solid var(--amber-border); background:linear-gradient(180deg,#fdf9ec,#ffffff 55%); }
.vra-hero-top{ display:flex; justify-content:space-between; gap:24px; flex-wrap:wrap; }
.vra-eyebrow{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.vra-meta-chip{ font-family:'Roboto Mono',monospace; font-size:12px; background:var(--surface); border:1px solid var(--border); color:var(--grey); border-radius:999px; padding:3px 10px; }
.vra-verdict{ font-size:33px; font-weight:800; line-height:1.18; letter-spacing:-.02em; margin:0; }
.vra-verdict-path{ color:var(--red-dark); } .vra-verdict-ben{ color:var(--green-dark); } .vra-verdict-dec{ color:#7a4d00; }
.vra-verdict-sub{ font-size:14.5px; color:var(--grey); margin-top:8px; line-height:1.5; max-width:560px; }
.vra-prob{ text-align:right; min-width:190px; }
.vra-prob-num{ font-size:52px; font-weight:800; letter-spacing:-.03em; line-height:1; }
.vra-prob-label{ font-size:12.5px; color:var(--grey); font-weight:600; text-transform:uppercase; letter-spacing:.05em; margin-top:6px; }
.vra-probbar{ position:relative; height:10px; border-radius:999px; margin-top:22px; background:linear-gradient(90deg,#0b7a37 0%,#a8c686 38%,#f9ab00 62%,#b91c1c 100%); }
.vra-probbar-marker{ position:absolute; top:50%; width:20px; height:20px; border-radius:50%; background:#fff; border:3.5px solid var(--ink); transform:translate(-50%,-50%); box-shadow:0 1px 5px rgba(0,0,0,.3); }
.vra-probbar-scale{ display:flex; justify-content:space-between; font-size:11.5px; color:var(--faint); margin-top:7px; font-weight:500; }
.vra-badge-down{ display:inline-flex; align-items:center; gap:7px; background:var(--amber-tint); border:1px solid var(--amber-border); color:#7a4d00; font-weight:600; font-size:13.5px; border-radius:999px; padding:6px 13px; margin-top:14px; }
.vra-gatebar{ height:10px; border-radius:999px; background:#e8eaed; margin-top:20px; overflow:hidden; }
.vra-gatebar-fill{ height:100%; background:var(--amber-border); border-radius:999px; }
/* tiles */
.vra-tiles{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px; }
.vra-tile{ background:#fff; border:1px solid var(--card-border); border-radius:16px; padding:15px 16px; }
.vra-tile-num{ font-size:25px; font-weight:800; letter-spacing:-.01em; }
.vra-tile-label{ font-size:12.5px; color:var(--grey); margin-top:3px; line-height:1.45; }
.vra-tile-num .vra-red{ color:var(--red-dark); } .vra-tile-num .vra-amb{ color:var(--amber); }
/* evidence table */
.vra-table-wrap{ overflow-x:auto; border:1px solid var(--card-border); border-radius:16px; background:#fff; }
table.vra-table{ border-collapse:collapse; width:100%; font-size:13.5px; min-width:640px; }
.vra-table th{ text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--grey); background:var(--surface); padding:11px 14px; border-bottom:1px solid var(--border); }
.vra-table td{ padding:11px 14px; border-bottom:1px solid #eef0f2; vertical-align:top; line-height:1.5; }
.vra-table tr:last-child td{ border-bottom:none; }
.vra-table tr{ transition:background .12s ease; } .vra-table tbody tr:hover{ background:#f8fbf9; }
.vra-src{ font-weight:600; white-space:nowrap; }
.vra-rec{ font-family:'Roboto Mono',monospace; font-size:11.5px; color:var(--grey); white-space:nowrap; }
.chip{ display:inline-block; font-size:11.5px; font-weight:600; border-radius:999px; padding:2.5px 10px; white-space:nowrap; }
.chip-path{ background:var(--red-tint); color:var(--red-dark); border:1px solid #f2b8b5; }
.chip-ben{ background:var(--green-tint); color:var(--green-dark); border:1px solid #a3d9b1; }
.chip-neu{ background:#f1f3f4; color:var(--grey); border:1px solid var(--border); }
.chip-mat{ background:var(--red-tint); color:var(--red-dark); border:1px solid #f2b8b5; }
.chip-not{ background:var(--amber-tint); color:var(--amber); border:1px solid var(--amber-border); }
.chip-min{ background:#f1f3f4; color:var(--grey); border:1px solid var(--border); }
.chip-ok{ background:var(--green-tint); color:var(--green-dark); border:1px solid #a3d9b1; }
.chip-fail{ background:var(--red-tint); color:var(--red-dark); border:1px solid #f2b8b5; }
.chip-none{ background:#f1f3f4; color:var(--grey); border:1px solid var(--border); }
/* analysis cards */
.vra-cards{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.vra-card{ background:#fff; border:1px solid var(--card-border); border-radius:16px; padding:17px; transition:box-shadow .18s ease, transform .18s ease; }
.vra-card:hover{ box-shadow:0 6px 18px rgba(32,33,36,.09); transform:translateY(-1px); }
.vra-card-head{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; margin-bottom:8px; }
.vra-card-title{ font-size:15px; font-weight:700; }
.vra-card p{ font-size:13px; color:var(--grey); line-height:1.55; margin:0 0 6px; }
.vra-bar-row{ margin-top:11px; }
.vra-bar-label{ display:flex; justify-content:space-between; font-size:12px; color:var(--grey); font-weight:500; margin-bottom:5px; }
.vra-bar-label b{ color:var(--ink); font-weight:700; }
.vra-bar{ height:8px; background:#e8eaed; border-radius:999px; overflow:hidden; }
.vra-bar-fill{ height:100%; border-radius:999px; }
.vra-fill-green{ background:var(--green); } .vra-fill-red{ background:var(--red); } .vra-fill-blue{ background:#1a73e8; } .vra-fill-amber{ background:var(--amber-border); }
.vra-lean-chips{ display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
/* reviewer */
.vra-callout{ border-radius:16px; padding:15px 18px; font-size:14px; line-height:1.55; margin-bottom:14px; }
.vra-callout-amber{ background:var(--amber-tint); border:1px solid var(--amber-border); }
.vra-callout-green{ background:var(--green-tint); border:1px solid #a3d9b1; }
.vra-families{ display:flex; gap:7px; flex-wrap:wrap; margin:4px 0 16px; }
.vra-fam{ background:var(--surface); border:1px solid var(--border); border-radius:999px; padding:4px 12px; font-size:12.5px; font-weight:500; color:var(--grey); }
.vra-crit{ display:flex; gap:12px; padding:12px 4px; border-bottom:1px solid #eef0f2; align-items:flex-start; }
.vra-crit:last-child{ border-bottom:none; }
.vra-crit-body{ flex:1; font-size:13.5px; line-height:1.55; }
.vra-crit-check{ font-family:'Roboto Mono',monospace; font-size:11px; color:var(--faint); display:block; margin-bottom:2px; }
/* designs */
.vra-design{ display:flex; gap:16px; background:#fff; border:1px solid var(--card-border); border-radius:16px; padding:18px; margin-bottom:12px; }
.vra-design-num{ flex:0 0 auto; width:34px; height:34px; border-radius:50%; background:var(--green); color:#fff; font-weight:700; font-size:16px; display:flex; align-items:center; justify-content:center; }
.vra-design-body{ flex:1; }
.vra-design-title{ font-size:15.5px; font-weight:700; margin:2px 0 6px; }
.vra-design-why{ font-size:13.5px; color:var(--grey); line-height:1.55; margin:0 0 12px; }
.vra-design-cols{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.vra-sup{ border-radius:12px; padding:11px 13px; font-size:13px; line-height:1.5; }
.vra-sup-path{ background:#fdf4f3; border:1px solid #f2b8b5; }
.vra-sup-ben{ background:#f0f8f2; border:1px solid #a3d9b1; }
.vra-sup h4{ margin:0 0 5px; font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; }
.vra-sup-path h4{ color:var(--red-dark); } .vra-sup-ben h4{ color:var(--green-dark); }
/* states */
.vra-empty{ text-align:center; border:1.5px dashed var(--border); border-radius:20px; padding:38px 26px; margin-top:22px; color:var(--grey); }
.vra-empty h3{ color:var(--ink); font-size:19px; margin:0 0 8px; }
.vra-empty p{ font-size:14px; line-height:1.6; margin:0 auto; max-width:520px; }
.vra-empty code{ background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:1px 6px; font-family:'Roboto Mono',monospace; font-size:12.5px; }
.vra-loading{ border:1px solid var(--card-border); border-radius:20px; padding:26px 28px; margin-top:22px; background:#fff; }
.vra-loading h3{ margin:0 0 6px; font-size:19px; }
.vra-loading p{ color:var(--grey); font-size:13.5px; margin:0 0 18px; }
.vra-skel{ height:14px; border-radius:7px; background:linear-gradient(90deg,#eef0f2 25%,#f7f8f9 50%,#eef0f2 75%); background-size:200% 100%; animation:vra-shimmer 1.3s infinite; margin-bottom:12px; }
@keyframes vra-shimmer{ 0%{ background-position:200% 0; } 100%{ background-position:-200% 0; } }
.vra-stages{ display:flex; gap:7px; flex-wrap:wrap; margin-bottom:18px; }
.vra-stage{ font-size:12px; font-weight:600; color:var(--grey); background:var(--surface); border:1px solid var(--border); border-radius:999px; padding:4px 11px; }
.vra-narrative{ background:var(--surface); border:1px solid var(--card-border); border-radius:16px; padding:16px 18px; font-size:13.5px; line-height:1.65; color:#3c4043; }
.vra-result-foot{ font-size:12.5px; color:var(--faint); line-height:1.6; margin-top:16px; }
.vra-footer{ border-top:1px solid var(--border); margin-top:42px; padding:20px 2px 8px; font-size:13px; color:var(--grey); line-height:1.6; }
.vra-footer a{ color:var(--green-dark); }
/* gradio chrome */
.vra-wrap button.primary, .vra-wrap .primary{ background:var(--green) !important; border-color:var(--green) !important; }
.vra-wrap button{ transition:transform .12s ease, box-shadow .12s ease, background .12s ease; }
.vra-wrap button:hover{ transform:translateY(-1px); box-shadow:0 4px 12px rgba(32,33,36,.14); }
.vra-example-btn{ font-weight:600 !important; }
footer{ display:none !important; }
@media (max-width:820px){
  .vra-stats{ grid-template-columns:repeat(2,1fr); }
  .vra-tiles{ grid-template-columns:repeat(2,1fr); }
  .vra-cards{ grid-template-columns:1fr; }
  .vra-hero-text h1{ font-size:31px; }
  .vra-verdict{ font-size:26px; }
  .vra-prob{ text-align:left; } .vra-prob-num{ font-size:42px; }
  .vra-design-cols{ grid-template-columns:1fr; }
  .vra-design{ flex-direction:column; gap:10px; }
}
"""

# ---------------------------------------------------------------------------
# Rendering helpers (pure functions of the pipeline run state)
# ---------------------------------------------------------------------------


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _pct(x) -> float:
    try:
        return max(0.0, min(100.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _dir_chip(direction: str) -> str:
    d = (direction or "unknown").lower()
    cls = {"pathogenic": "chip-path", "benign": "chip-ben"}.get(d, "chip-neu")
    return f'<span class="chip {cls}">{esc(d)}</span>'


def _sev_chip(severity: str) -> str:
    s = (severity or "minor").lower()
    cls = {"material": "chip-mat", "notable": "chip-not"}.get(s, "chip-min")
    return f'<span class="chip {cls}">{esc(s)}</span>'


def _status_chip(status: str) -> str:
    s = (status or "").lower()
    label, cls = {
        "ok": ("Completed", "chip-ok"),
        "no_content": ("No content", "chip-none"),
        "failed": ("Failed", "chip-fail"),
        "timeout": ("Timed out", "chip-not"),
    }.get(s, (s or "unknown", "chip-none"))
    return f'<span class="chip {cls}">{esc(label)}</span>'


def _bar(label: str, value_text: str, pct: float, fill: str) -> str:
    return (
        f'<div class="vra-bar-row"><div class="vra-bar-label">'
        f"<span>{esc(label)}</span><b>{esc(value_text)}</b></div>"
        f'<div class="vra-bar"><div class="vra-bar-fill {fill}" '
        f'style="width:{_pct(pct):.1f}%"></div></div></div>')


_ANALYSIS_TITLES = {
    "population_context": "Population context",
    "predictor_agreement": "Predictor agreement",
    "score_percentiles": "Score percentiles",
}


def _analysis_extras(a: dict) -> str:
    """Percentile / agreement bars for one analysis, when its results
    carry the numbers (never rendered for missing data)."""
    res = a.get("results") or {}
    out = []
    if a["name"] == "population_context":
        pct = res.get("af_percentile_in_local_test_set")
        if pct is not None:
            out.append(_bar("Allele-frequency percentile in the local test set",
                            f"{float(pct):.1f}th", pct, "vra-fill-blue"))
        if res.get("rarity_class"):
            out.append(f'<p style="margin-top:9px">Rarity class: '
                       f"<b>{esc(res['rarity_class'])}</b></p>")
    elif a["name"] == "predictor_agreement":
        frac = res.get("pairwise_agreement_fraction")
        if frac is not None:
            out.append(_bar("Pairwise predictor agreement",
                            f"{float(frac) * 100:.0f}%", float(frac) * 100,
                            "vra-fill-green"))
        if res.get("consensus"):
            out.append(f'<p style="margin-top:9px">Consensus: '
                       f"<b>{esc(res['consensus'])}</b></p>")
        leans = res.get("leans") or {}
        if leans:
            chips = "".join(
                f'<span class="chip {_dir_cls(v)}">{esc(k)}: {esc(v)}</span>'
                for k, v in leans.items())
            out.append(f'<div class="vra-lean-chips">{chips}</div>')
    elif a["name"] == "score_percentiles":
        for key, label in (("am_score", "AlphaMissense"),
                           ("revel_score", "REVEL")):
            pct = res.get(key + "_percentile_in_local_test_set")
            val = res.get(key)
            if pct is not None and val is not None:
                out.append(_bar(f"{label} percentile in the local test set",
                                f"{float(val):.3f} · {float(pct):.1f}th",
                                pct, "vra-fill-blue"))
    return "".join(out)


def _dir_cls(lean_word: str) -> str:
    w = (lean_word or "").lower()
    if w.startswith("pathogenic"):
        return "chip-path"
    if w.startswith("benign"):
        return "chip-ben"
    return "chip-neu"


def render_result(state: dict) -> str:
    rec = state["record"]
    gate = state["gate"]
    j = state["judgment"]
    review = state.get("review") or {}
    critiques = review.get("critiques") or []
    families = review.get("families") or []
    analyses = state.get("analyses") or []
    evidence = state.get("evidence") or []
    designs = (state.get("design") or {}).get("designs") or []
    passed = bool(gate["passed"])
    lean = j.get("lean", "")
    prob = j.get("model_prob_pathogenic")

    genomic = f"{rec.get('chrom')}:{rec.get('pos')} {rec.get('ref')}>{rec.get('alt')}"
    eyebrow = (
        f'<div class="vra-eyebrow">'
        f'<span class="vra-meta-chip">{esc(rec.get("gene"))}</span>'
        f'<span class="vra-meta-chip">{esc(genomic)}</span>'
        f'<span class="vra-meta-chip">ClinVar allele {esc(rec.get("allele_id"))}</span>'
        f'<span class="vra-meta-chip">{esc(rec.get("name"))}</span></div>')

    # ---- verdict hero -------------------------------------------------
    if not passed:
        hero_cls, verdict_cls = "vra-hero-dec", "vra-verdict-dec"
        title = "Declined — insufficient evidence"
        sub = ("The agent refuses to conclude on this variant. "
               f"Reason: {gate.get('reason', '')}. The experiment designs "
               "below are the fastest route to evidence that would settle it.")
        n_have, n_need = gate.get("evidence_count", 0), gate.get("min_evidence", 3)
        fill = (100.0 * n_have / n_need) if n_need else 0.0
        right = (
            f'<div class="vra-prob"><div class="vra-prob-num">'
            f"{esc(n_have)} of {esc(n_need)}</div>"
            f'<div class="vra-prob-label">evidence items vs the bar</div></div>')
        bar = (f'<div class="vra-gatebar"><div class="vra-gatebar-fill" '
               f'style="width:{_pct(fill):.0f}%"></div></div>')
        if gate.get("missing"):
            chips = "".join(f'<span class="vra-fam">missing: {esc(m)}</span>'
                            for m in gate["missing"])
            bar += f'<div class="vra-families" style="margin-top:12px">{chips}</div>'
    else:
        if lean == "pathogenic":
            hero_cls, verdict_cls = "vra-hero-path", "vra-verdict-path"
        else:
            hero_cls, verdict_cls = "vra-hero-ben", "vra-verdict-ben"
        strength = (j.get("strength") or "").strip()
        title = (f"{strength.title()} " if strength else "") \
            + f"{lean}-leaning evidence summary"
        sub = ("Evidence summary only — not a clinical classification. "
               f"Judgment basis: {j.get('basis', '')}.")
        if prob is not None:
            right = (
                f'<div class="vra-prob"><div class="vra-prob-num">'
                f"{float(prob):.3f}</div>"
                f'<div class="vra-prob-label">calibrated P(pathogenic)</div></div>')
            bar = (
                f'<div class="vra-probbar"><div class="vra-probbar-marker" '
                f'style="left:{float(prob) * 100:.1f}%"></div></div>'
                '<div class="vra-probbar-scale"><span>0 · benign</span>'
                "<span>0.5</span><span>1 · pathogenic</span></div>")
        elif j.get("evidence_score") is not None:
            right = (
                f'<div class="vra-prob"><div class="vra-prob-num">'
                f"{esc(j['evidence_score'])}</div>"
                f'<div class="vra-prob-label">evidence score (no recorded '
                "calibrated probability for this variant)</div></div>")
            bar = ""
        else:
            right, bar = "", ""
    badge = ""
    if review.get("downgraded"):
        badge = (
            f'<div><span class="vra-badge-down">Reviewer downgraded: '
            f"{esc(review.get('strength_before'))} → "
            f"{esc(review.get('strength_after'))}</span></div>")
        if review.get("downgrade_reason"):
            badge += (f'<p class="vra-verdict-sub" style="margin-top:8px">'
                      f"{esc(review['downgrade_reason'])}</p>")
    hero = (f'<div class="vra-hero {hero_cls}">{eyebrow}'
            f'<div class="vra-hero-top"><div>'
            f'<h2 class="vra-verdict {verdict_cls}">{esc(title)}</h2>'
            f'<p class="vra-verdict-sub">{esc(sub)}</p>{badge}</div>'
            f"{right}</div>{bar}</div>")

    # ---- stat tiles ----------------------------------------------------
    n_ok = sum(1 for a in analyses if a.get("status") == "ok")
    n_mat = sum(1 for c in critiques if c.get("severity") == "material")
    n_not = sum(1 for c in critiques if c.get("severity") == "notable")
    n_min = sum(1 for c in critiques if c.get("severity") == "minor")
    tiles = f"""
<div class="vra-tiles">
  <div class="vra-tile"><div class="vra-tile-num">{esc(gate.get('evidence_count', len(evidence)))}</div>
    <div class="vra-tile-label">evidence items gathered (bar: {esc(gate.get('min_evidence', 3))} to conclude)</div></div>
  <div class="vra-tile"><div class="vra-tile-num">{len(families)}</div>
    <div class="vra-tile-label">independent evidence families after de-correlation</div></div>
  <div class="vra-tile"><div class="vra-tile-num">{n_ok}/{len(analyses)}</div>
    <div class="vra-tile-label">agent analyses completed in the sandbox</div></div>
  <div class="vra-tile"><div class="vra-tile-num">{len(critiques)}</div>
    <div class="vra-tile-label">reviewer findings — <span class="vra-red"><b>{n_mat} material</b></span> · <span class="vra-amb"><b>{n_not} notable</b></span> · {n_min} minor</div></div>
</div>"""

    # ---- evidence table -------------------------------------------------
    rows = []
    for i, e in enumerate(evidence, 1):
        live = ' <span class="chip chip-ok">live</span>' if e.get("live") else ""
        rows.append(
            f"<tr><td>{i}</td><td class='vra-src'>{esc(e.get('source'))}{live}</td>"
            f"<td class='vra-rec'>{esc(e.get('source_id'))}</td>"
            f"<td>{esc(e.get('detail'))}</td>"
            f"<td>{_dir_chip(e.get('direction', 'unknown'))}</td></tr>")
    evidence_html = (
        '<h3 class="vra-section-title">Evidence — every claim cited</h3>'
        '<p class="vra-section-sub">Retrieved records and the agent\'s own '
        "computed analyses. Direction is what each item supports, not the "
        "verdict.</p>"
        f'<div class="vra-table-wrap"><table class="vra-table"><thead><tr>'
        "<th>#</th><th>Source</th><th>Record</th><th>Detail</th>"
        f"<th>Direction</th></tr></thead><tbody>{''.join(rows)}</tbody>"
        "</table></div>") if rows else ""

    # ---- analyses cards --------------------------------------------------
    cards = []
    for a in analyses:
        cards.append(
            f'<div class="vra-card"><div class="vra-card-head">'
            f'<span class="vra-card-title">'
            f"{esc(_ANALYSIS_TITLES.get(a.get('name'), a.get('name')))}</span>"
            f"{_status_chip(a.get('status'))}</div>"
            f"<p>{esc(a.get('summary') or a.get('error') or '')}</p>"
            f"{_analysis_extras(a)}</div>")
    analyses_html = (
        '<h3 class="vra-section-title">Analyses the agent ran itself</h3>'
        '<p class="vra-section-sub">Small programs the agent generated and '
        "executed in a no-network sandbox (30 s timeout). Only analyses "
        "with real computed content count as evidence; failures are "
        "shown, never hidden.</p>"
        f'<div class="vra-cards">{"".join(cards)}</div>') if cards else ""

    # ---- reviewer ---------------------------------------------------------
    rev_parts = ['<h3 class="vra-section-title">Reviewer critique</h3>',
                 '<p class="vra-section-sub">An adversarial stage checked '
                 "independence, direction conflicts, missing evidence "
                 "classes, calibration caveats, and whether the verdict "
                 "strength matches its independent support. It may "
                 "downgrade confidence language one step; it can never "
                 "upgrade a verdict or reverse a decline.</p>"]
    if families:
        fams = "".join(f'<span class="vra-fam">{esc(f)}</span>' for f in families)
        rev_parts.append(f'<div class="vra-families">{fams}</div>')
    if review.get("downgraded"):
        rev_parts.append(
            '<div class="vra-callout vra-callout-amber"><strong>Downgrade '
            f"applied:</strong> {esc(review.get('strength_before'))} → "
            f"{esc(review.get('strength_after'))}"
            + (f" — {esc(review['downgrade_reason'])}"
               if review.get("downgrade_reason") else "") + "</div>")
    if review.get("decline_upheld"):
        rev_parts.append(
            '<div class="vra-callout vra-callout-green"><strong>Decline '
            "upheld.</strong> The reviewer checked the refusal against "
            "the evidence state and found it consistent.</div>")
    for c in critiques:
        rev_parts.append(
            f'<div class="vra-crit">{_sev_chip(c.get("severity"))}'
            f'<div class="vra-crit-body"><span class="vra-crit-check">'
            f"{esc(c.get('check'))}</span>{esc(c.get('finding'))}</div></div>")
    if review.get("llm_critique"):
        rev_parts.append(
            '<div class="vra-callout vra-callout-green"><strong>LLM '
            "critique (advisory only):</strong> "
            f"{esc(review['llm_critique'])}</div>")
    reviewer_html = "".join(rev_parts) if critiques or families else ""

    # ---- experiment designs ----------------------------------------------
    design_cards = []
    for d in designs:
        design_cards.append(
            f'<div class="vra-design"><div class="vra-design-num">'
            f"{esc(d.get('priority'))}</div><div class='vra-design-body'>"
            f'<div class="vra-design-title">{esc(d.get("assay_type"))}</div>'
            f'<span class="chip chip-neu">supplies: {esc(d.get("supplies"))}</span>'
            f'<p class="vra-design-why">{esc(d.get("rationale"))}</p>'
            f'<div class="vra-design-cols">'
            f'<div class="vra-sup vra-sup-path"><h4>Supports pathogenic</h4>'
            f"{esc(d.get('supports_pathogenic'))}</div>"
            f'<div class="vra-sup vra-sup-ben"><h4>Supports benign</h4>'
            f"{esc(d.get('supports_benign'))}</div>"
            "</div></div></div>")
    designs_html = (
        '<h3 class="vra-section-title">Validation experiment designs</h3>'
        '<p class="vra-section-sub">The experiments that would most '
        "efficiently settle this variant, in priority order — with the "
        "deciding results stated in advance.</p>"
        + "".join(design_cards)) if design_cards else ""

    # ---- narrative + provenance -------------------------------------------
    narrative_html = ""
    if state.get("narrative"):
        narrative_html = (
            '<h3 class="vra-section-title">Narrative</h3>'
            f'<div class="vra-narrative">{esc(state["narrative"])}</div>')
    notes = state.get("notes") or []
    foot = (f"Plan mode: {esc(state.get('plan_mode', 'template'))} · "
            "LLM mode: offline · Gatherers: ClinVar (local records), "
            "gnomAD (recorded lookup), PubMed (not queried — offline).")
    if notes:
        foot += " " + " ".join(esc(n) for n in notes)
    foot_html = f'<p class="vra-result-foot">{foot}</p>'

    return hero + tiles + evidence_html + analyses_html + reviewer_html \
        + designs_html + narrative_html + foot_html


def loading_html(variant: str) -> str:
    stages = "".join(
        f'<span class="vra-stage">{s}</span>' for s in
        ("Plan", "Gather evidence", "Run analyses", "Judge",
         "Review", "Design experiments", "Write dossier"))
    return (
        f'<div class="vra-loading"><h3>Researching '
        f"{esc(variant)}…</h3><p>The agent is working through its "
        "pipeline. This usually takes a few seconds.</p>"
        f'<div class="vra-stages">{stages}</div>'
        '<div class="vra-skel" style="width:92%"></div>'
        '<div class="vra-skel" style="width:78%"></div>'
        '<div class="vra-skel" style="width:85%"></div>'
        '<div class="vra-skel" style="width:60%"></div></div>')


def empty_html() -> str:
    return (
        '<div class="vra-empty"><h3>Enter a variant to begin</h3>'
        "<p>Use a gene and change such as <code>ARSB:c.1178A&gt;C</code>, "
        "a ClinVar allele id such as <code>allele:20309</code>, or a "
        "genomic form such as <code>5:78839391:T&gt;G</code> — or pick "
        "one of the examples below.</p></div>")


def unresolvable_html(variant: str, message: str) -> str:
    return (
        '<div class="vra-empty"><h3>That variant could not be resolved</h3>'
        f"<p><code>{esc(variant)}</code> is not in the local temporal "
        "test set this demo runs on (27,748 variants). Nothing was "
        "guessed and no dossier was invented.</p>"
        f'<p style="margin-top:10px">{esc(message)}</p>'
        "<p style=\"margin-top:10px\">Try <code>ARSB:c.1178A&gt;C</code>, "
        "<code>NHERF1:c.328C&gt;G</code> or <code>allele:28034</code> "
        "from the examples below.</p></div>")


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------


def research(variant: str):
    """Run the full pipeline for one variant.

    Generator: yields a loading state first, then (result_html,
    dossier_markdown)."""
    variant = (variant or "").strip()
    if not variant:
        yield empty_html(), ""
        return
    yield loading_html(variant), ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            state = run(variant, out_dir=tmp, live=False)
            md = dossier_mod.render_dossier(state)
    except ValueError as e:
        yield unresolvable_html(variant, str(e)), ""
        return
    yield render_result(state), md


_EXAMPLES = [
    ("Pathogenic · reviewer downgrades", "ARSB:c.1178A>C"),
    ("Benign · strong verdict stands", "NHERF1:c.328C>G"),
    ("Declined · honest refusal", "allele:28034"),
]


def build() -> gr.Blocks:
    with gr.Blocks(title="Variant Research Agent", css=CSS) as app:
        with gr.Column(elem_classes="vra-wrap"):
            gr.HTML(HEADER_HTML)
            gr.HTML(STATS_HTML)
            gr.HTML('<div class="vra-input-label">Research a variant</div>')
            with gr.Row():
                inp = gr.Textbox(
                    label="Variant", show_label=False, scale=5,
                    placeholder="ARSB:c.1178A>C  |  allele:20309  |  "
                                "5:78839391:T>G")
                btn = gr.Button("Research this variant", variant="primary",
                                scale=1)
            with gr.Row():
                ex_btns = [gr.Button(label, elem_classes="vra-example-btn")
                           for label, _ in _EXAMPLES]
            result = gr.HTML(empty_html())
            with gr.Accordion("Full dossier (Markdown, exactly as the "
                              "pipeline writes it)", open=False):
                dossier_out = gr.Markdown()
            gr.HTML(FOOTER_HTML)
        btn.click(research, inputs=inp, outputs=[result, dossier_out])
        inp.submit(research, inputs=inp, outputs=[result, dossier_out])
        for b, (_, query) in zip(ex_btns, _EXAMPLES):
            b.click(lambda q=query: q, outputs=inp).then(
                research, inputs=inp, outputs=[result, dossier_out])
    return app


if __name__ == "__main__":
    build().launch()
