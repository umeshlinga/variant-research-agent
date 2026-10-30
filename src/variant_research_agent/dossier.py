"""Dossier writer: Markdown dossier + JSON trace.

The deterministic sections (variant, verdict, evidence, missing
evidence, provenance) are rendered in code in BOTH modes — every
claim cites a source identifier (R2). Dossier v2 (Phase 3) adds the
reviewer critique and validation experiment design sections, both
rendered from the deterministic stage outputs; an LLM critique or
designer note, when present, appears in its own labelled subsection
and never alters the verdict, the numbers, or the evidence table. In
LLM mode the model may also add one clearly-marked narrative section
written only from the gathered evidence items. In offline mode the
narrative is an extractive template built from the same items.
"""
from __future__ import annotations

import json
from pathlib import Path

DECLINE_LINE = "insufficient evidence — remains VUS"

# What evidence would be needed — named when the gate declines (R3)
MISSING_CANDIDATES = [
    ("AlphaMissense", "a precomputed missense predictor score (AlphaMissense)"),
    ("REVEL", "a REVEL predictor score"),
    ("gnomAD", "a successful gnomAD population-frequency lookup"),
    ("PubMed", "published literature on this exact variant (PubMed)"),
    ("ClinVar", "a ClinVar record at the freeze date"),
]


def missing_evidence(evidence: list[dict]) -> list[str]:
    have = " ".join(e["source"] for e in evidence)
    return [text for key, text in MISSING_CANDIDATES if key not in have]


def render_dossier(state: dict) -> str:
    rec = state["record"]
    gate = state["gate"]
    j = state["judgment"]
    ev = state["evidence"]
    lines = [
        f"# Variant Research Dossier — {rec['name']}",
        "",
        f"**Gene:** {rec['gene']}  ",
        f"**Genomic (GRCh38):** {rec['chrom']}:{rec['pos']} {rec['ref']}>{rec['alt']}  ",
        f"**ClinVar allele ID:** {rec['allele_id']}  ",
        f"**Local record:** {rec['dataset']} (vus-evidence-agent processed data)",
        "",
        "## Verdict",
        "",
    ]
    if not gate["passed"]:
        lines += [
            f"**DECLINED — {DECLINE_LINE}.**",
            "",
            f"The decline gate refused to conclude: {gate['reason']} "
            f"({gate['evidence_count']} independent evidence item(s), "
            f"minimum {gate['min_evidence']}).",
        ]
    else:
        lines += [
            f"**Evidence summary — {j['strength']} {j['lean']}-leaning** "
            "(not a clinical classification).",
            "",
        ]
        if j["model_prob_pathogenic"] is not None:
            lines.append(
                f"Calibrated P(pathogenic) = {j['model_prob_pathogenic']:.3f} "
                "from the GBM+R model (vus-evidence-agent MODEL_REPORT_6: "
                "AUROC 0.9705, ECE 0.0248, Brier 0.0625, temporal test set).")
        else:
            lines.append(
                f"Evidence score = {j['evidence_score']:+d} (transparent "
                "direction sum; NOT a calibrated probability — the GBM+R "
                "model has no recorded prediction for this variant).")
    review = state.get("review") or {}
    if review.get("downgraded"):
        lines += [
            "",
            f"**Reviewer downgrade:** the reviewer reduced the confidence "
            f"language from **{review['strength_before']}** to "
            f"**{review['strength_after']}** ({review['downgrade_reason']}). "
            "The lean and the probability are unchanged — the reviewer may "
            "only weaken confidence language, never strengthen it, and it "
            "cannot change the verdict's direction or the gate outcome.",
        ]
    lines += ["", "## Judgment basis", ""]
    lines += [f"- {r}" for r in j["rationale"]]
    lines += ["", "## Evidence (every claim cited)", ""]
    if ev:
        lines += ["| # | Source | Record | Detail | Direction |",
                  "|---|--------|--------|--------|-----------|"]
        for i, e in enumerate(ev, 1):
            lines.append(f"| {i} | {e['source']} | {e['source_id']} | "
                         f"{e['detail']} | {e['direction']} |")
    else:
        lines.append("(no evidence items retrieved)")
    analyses = state.get("analyses") or []
    if analyses:
        lines += ["", "## Analyses run by the agent", "",
                  "Each analysis below is a Python script the agent "
                  "generated and executed in a no-network sandbox "
                  "(30 s timeout). Script sources and full outputs are "
                  "in the JSON trace. Only analyses with real computed "
                  "content count as evidence; failures are shown, "
                  "never hidden.", ""]
        for a in analyses:
            head = (f"- **{a['name']}** [{a.get('origin', 'template')} "
                    f"script, sha {a['script_sha256'][:12]}, "
                    f"{a['duration_s']:.2f}s] — status: **{a['status']}**")
            lines.append(head)
            if a["status"] == "ok":
                lines.append(f"  - {a['summary']}")
                lines.append(
                    "  - Counted as evidence: "
                    f"<ANALYSIS:{a['name']}:{a['script_sha256'][:12]}>")
            elif a["status"] == "no_content":
                lines.append(f"  - {a['summary']}")
                lines.append("  - Not counted as evidence (no computed "
                             "content — a needed datum was unavailable).")
            else:
                lines.append(f"  - FAILED: {a.get('error') or 'unknown error'}")
                lines.append("  - Not counted as evidence.")
    if review:
        lines += ["", "## Reviewer critique", "",
                  "An adversarial reviewer stage checked this draft "
                  "deterministically: evidence independence, direction "
                  "conflicts, missing evidence classes, calibration "
                  "caveats, and whether the verdict strength matches "
                  "its independent support. Severity: **material** "
                  "findings can downgrade the confidence language one "
                  "step; **notable** findings are real weaknesses the "
                  "reader must see; **minor** findings are context. "
                  "The reviewer can never upgrade a verdict or reverse "
                  "a decline.", ""]
        if not gate["passed"]:
            lines.append("This case was DECLINED by the gate. The "
                         "reviewer has no power to reverse a decline "
                         "(R3) and records it as upheld; the critiques "
                         "below explain the evidence state the decline "
                         "rests on.")
            lines.append("")
        if review.get("families"):
            lines.append("- Independent evidence families present: "
                         + ", ".join(review["families"])
                         + f" ({len(review['families'])})")
        for c in review.get("critiques", []):
            lines.append(f"- **[{c['severity']}] {c['check']}** — {c['finding']}")
        if review.get("downgraded"):
            lines.append(f"- **Downgrade applied:** "
                         f"{review['strength_before']} → "
                         f"{review['strength_after']} "
                         f"({review['downgrade_reason']}).")
        if review.get("llm_critique"):
            lines += ["", "### LLM reviewer note (model-written, advisory only)",
                      "",
                      "The following was written by the configured LLM. "
                      "It is NOT part of the deterministic critique and "
                      "had no effect on the verdict, the gate, or any "
                      "downgrade.", "", review["llm_critique"]]
    design = state.get("design") or {}
    designs = design.get("designs") or []
    if designs:
        lines += ["", "## Validation experiment design", ""]
        if not gate["passed"]:
            lines.append("The gate declined for insufficient evidence. "
                         "These are the experiments that would most "
                         "efficiently supply what is missing, in "
                         "priority order — for each, the result that "
                         "would support pathogenic and the result that "
                         "would support benign are stated in advance.")
        else:
            lines.append("Experiments that would most efficiently "
                         "settle this variant, in priority order. They "
                         "target the evidence classes this verdict does "
                         "NOT rest on; for each, the result that would "
                         "support pathogenic and the result that would "
                         "support benign are stated in advance.")
        lines.append("")
        for d in designs:
            lines += [
                f"**{d['priority']}. {d['assay_type']}**",
                "",
                f"- Supplies: {d['supplies']}",
                f"- Why this experiment: {d['rationale']}",
                f"- Result supporting pathogenic: {d['supports_pathogenic']}",
                f"- Result supporting benign: {d['supports_benign']}",
                "",
            ]
        if design.get("llm_note"):
            lines += ["### LLM designer note (model-written, advisory only)",
                      "", design["llm_note"], ""]
    if not gate["passed"] and gate["missing"]:
        lines += ["", "## Missing evidence (what would be needed)", ""]
        lines += [f"- {m}" for m in gate["missing"]]
    if state.get("notes"):
        lines += ["", "## Run notes", ""]
        lines += [f"- {n}" for n in state["notes"]]
    lines += ["", "## Narrative", "", state.get("narrative", ""), "",
              "## Provenance", "",
              f"- Plan mode: {state['plan_mode']}; LLM mode: {state['llm_usage']['mode']}",
              f"- Gatherers: ClinVar (local processed data), gnomAD "
              f"({'live' if state['live'] else 'recorded lookup'}), PubMed "
              f"({'live' if state['live'] else 'not queried — offline'})",
              f"- Compute stage: {len(state.get('analyses') or [])} agent "
              "analyses executed in a no-network sandbox (30 s timeout); "
              "script sources + outputs are in the JSON trace.",
              f"- Reviewer stage: deterministic critique, "
              f"{len((state.get('review') or {}).get('critiques', []))} "
              "finding(s); downgrade applied: "
              f"{'yes' if (state.get('review') or {}).get('downgraded') else 'no'}; "
              "LLM critique: "
              f"{'present (advisory)' if (state.get('review') or {}).get('llm_critique') else 'absent'}.",
              f"- Experiment designer: "
              f"{len((state.get('design') or {}).get('designs', []))} "
              "validation experiment design(s) proposed.",
              "- Temporal integrity (R1): only prediction-time (frozen "
              "2024-01) records were used as evidence; the later ClinVar "
              "reclassification was never loaded.",
              "- Not for clinical use. Research project only.",
              ""]
    return "\n".join(lines)


def write_outputs(state: dict, dossier_md: str, out_dir: Path,
                  stamp: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{state['record']['gene']}_allele{state['record']['allele_id']}_{stamp}"
    md_path = out_dir / f"{slug}.md"
    json_path = out_dir / f"{slug}.json"
    md_path.write_text(dossier_md)
    trace = {
        "query": state["query"],
        "record": state["record"],
        "plan": state["plan"],
        "plan_mode": state["plan_mode"],
        "evidence": state["evidence"],
        "analyses": state.get("analyses", []),
        "judgment": state["judgment"],
        "gate": state["gate"],
        "review": state.get("review", {}),
        "design": state.get("design", {}),
        "narrative": state.get("narrative", ""),
        "notes": state.get("notes", []),
        "events": state.get("events", []),
        "llm_usage": state["llm_usage"],
        "live": state["live"],
        "generated_at": stamp,
    }
    json_path.write_text(json.dumps(trace, indent=2))
    return {"dossier": str(md_path), "trace": str(json_path)}
