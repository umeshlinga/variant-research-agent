"""Hugging Face Space skeleton for the Variant Research Agent.

STATUS: SKELETON — prepared for release, NOT deployed.

Wraps the CLI pipeline for a single variant and renders the dossier.
Default mode is OFFLINE (deterministic, local data only, no LLM, no
network gatherers), matching the benchmark configuration.

Deployment notes (read before pushing this anywhere):
  * The Space must contain the whole project (src/ alongside this
    file's parent) — the sys.path shim below assumes the repo layout
    <space>/space/app.py + <space>/src/variant_research_agent/.
  * The agent reads the vus-evidence-agent processed tables in place.
    A Space has no such directory: set VRA_VUS_HOME to a bundled copy
    of the processed tables, or the app will resolve nothing. The
    tables are the source project's data — check its licence/terms
    before redistributing them inside a Space.
  * Live mode and LLM mode are intentionally OFF here. Enabling them
    is a deliberate deployment decision (secrets for LLM_API_KEY via
    Space secrets; never hardcode a key).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Offline by default: deterministic, reproducible, no endpoint probing.
os.environ.setdefault("VRA_OFFLINE", "1")

# Repo layout shim: <repo>/space/app.py -> <repo>/src must be importable.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

import gradio as gr  # noqa: E402

from variant_research_agent import dossier as dossier_mod  # noqa: E402
from variant_research_agent.graph import run  # noqa: E402


def research(variant: str) -> tuple[str, str]:
    """Run the full pipeline for one variant; return (verdict, dossier)."""
    variant = (variant or "").strip()
    if not variant:
        return "Enter a variant first.", ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            state = run(variant, out_dir=tmp, live=False)
            md = dossier_mod.render_dossier(state)
    except ValueError as e:
        return f"Could not resolve that variant: {e}", ""
    gate, j = state["gate"], state["judgment"]
    if not gate["passed"]:
        verdict = (f"**DECLINED — insufficient evidence** "
                   f"({gate['evidence_count']} evidence items; {gate['reason']})")
    else:
        verdict = (f"**{j['strength']} {j['lean']}-leaning evidence summary** "
                   f"(basis: {j['basis']}, {gate['evidence_count']} evidence items)")
        if (state.get("review") or {}).get("downgraded"):
            verdict += " — reviewer downgraded the confidence language"
    return verdict, md


def build() -> gr.Blocks:
    with gr.Blocks(title="Variant Research Agent") as app:
        gr.Markdown(
            "# Variant Research Agent\n"
            "Variant in, auditable research dossier out — or an honest "
            "decline when the evidence is too thin. Offline mode: local "
            "data only, deterministic. **Not for clinical use.**")
        inp = gr.Textbox(
            label="Variant",
            placeholder="ARSB:c.1178A>C  |  allele:20309  |  5:78839391:T>G",
        )
        btn = gr.Button("Research this variant")
        verdict = gr.Markdown()
        out = gr.Markdown()
        btn.click(research, inputs=inp, outputs=[verdict, out])
    return app


if __name__ == "__main__":
    build().launch()
