"""LangGraph pipeline (Phase 1 fusion + Phase 2 compute + Phase 3
critique/design).

Stages: planner -> gather_clinvar -> gather_gnomad -> gather_pubmed
-> compute -> judge -> decline_gate -> reviewer -> experiment_designer
-> dossier_writer.

Orchestration pattern (events accounting, deterministic gate enforced
in code, LLM stages that degrade to templates offline) follows
multi-agent-evidence/src/graph.py; the evidence logic and decline
rule follow vus-evidence-agent (MIN_EVIDENCE = 3, R3). The compute
stage (Phase 2) runs agent-authored analyses in a no-network sandbox;
only analyses with real computed content join the evidence list. The
reviewer (Phase 3) deterministically critiques the draft judgment and
may downgrade its confidence language one step — it can never upgrade
or reverse the gate; the designer (Phase 3) proposes the validation
experiments that would settle the variant, declined cases included.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import compute as compute_mod
from . import designer as designer_mod
from . import dossier as dossier_mod
from . import gatherers
from . import reviewer as reviewer_mod
from .data import LocalData
from .judge import judge as judge_fn
from .llm import LLMClient, LLMError
from .model import CalibratedModelAdapter
from .schema import GateResult

MIN_EVIDENCE = 3  # BUILD_PLAN R3 — fewer than 3 independent items => decline


class State(TypedDict, total=False):
    query: str
    live: bool
    out_dir: str
    record: dict
    plan: list
    plan_mode: str
    evidence: list
    analyses: list
    judgment: dict
    gate: dict
    review: dict
    design: dict
    narrative: str
    notes: list
    events: list
    llm_usage: dict
    outputs: dict


class _Ctx:
    """Run-scoped collaborators (kept out of the serialisable state)."""

    def __init__(self, data: LocalData, llm: LLMClient):
        self.data = data
        self.model = CalibratedModelAdapter(data)
        self.llm = llm


def _template_plan(record: dict, live: bool) -> list[str]:
    steps = [
        "Resolve the variant against the local vus-evidence-agent tables "
        "(prediction-time records only, R1).",
        "Gather the frozen ClinVar status and precomputed predictors "
        "(AlphaMissense, REVEL, gene prior) from the local processed data.",
        "Gather population frequency from gnomAD "
        + ("via the live GraphQL API." if live
           else "from the recorded lookup in the local data."),
        "Gather literature from PubMed "
        + ("via E-utilities." if live else "(skipped in offline mode)."),
        "Run the agent's own analyses in a no-network sandbox "
        "(population context, predictor agreement, score percentiles); "
        "only analyses with real computed content become evidence.",
        "Judge with the calibrated GBM+R probability when a recorded "
        "prediction exists; otherwise fall back to transparent evidence scoring.",
        f"Apply the decline gate: fewer than {MIN_EVIDENCE} independent "
        "evidence items, or an indeterminate judgment, declines (R3).",
        "Reviewer stage: adversarial deterministic critique of the draft "
        "judgment (independence, conflicts, missing classes, calibration, "
        "strength vs support); it may downgrade confidence language one "
        "step but can never upgrade or reverse the gate.",
        "Experiment designer: propose the validation experiment(s) that "
        "would most efficiently settle the variant, stating in advance "
        "which result supports pathogenic and which supports benign.",
        "Write the dossier (Markdown + JSON trace) with every claim cited (R2).",
    ]
    if record.get("vep_consequence"):
        steps.insert(2, f"Consequence is {record['vep_consequence']}: "
                        "missense predictors are applicable evidence.")
    return steps


def build_graph(ctx: _Ctx):
    def node_planner(state: State) -> State:
        events = list(state.get("events", []))
        record = ctx.data.resolve(state["query"])
        if record is None:
            raise ValueError(
                f"variant not found in the local vus-evidence-agent data: "
                f"{state['query']!r}. Accepted forms: allele id, "
                "GENE:c.change, chr:pos:ref>alt, or a ClinVar name substring.")
        events.append(f"planner: resolved to allele {record.allele_id} "
                      f"({record.name}) from {record.dataset}")
        plan, mode = None, "template"
        if ctx.llm.available():
            try:
                raw = ctx.llm.chat(
                    "Write a short numbered investigation plan (max 7 steps) "
                    "for researching this genetic variant. Facts: "
                    f"gene={record.gene}, name={record.name}, "
                    f"consequence={record.vep_consequence}, "
                    f"ClinVar status at 2024-01 freeze={record.sig_then}. "
                    "Available evidence sources: frozen ClinVar + "
                    "AlphaMissense + REVEL (local), gnomAD, PubMed, plus "
                    "the agent's own sandboxed analyses of the gathered "
                    "data (population context, predictor agreement, "
                    "score percentiles). "
                    "A calibrated GBM+R model probability exists for some "
                    "variants. The plan must end with a decline gate: fewer "
                    "than 3 independent evidence items means no conclusion. "
                    "After the gate, a deterministic reviewer critiques "
                    "the judgment (it may only downgrade confidence "
                    "language) and an experiment designer proposes the "
                    "validation experiment that would settle the variant.",
                    label="planner", max_tokens=400)
                plan = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                mode = "llm"
            except LLMError:
                plan = None
        if not plan:
            plan = _template_plan(record.model_dump(), state.get("live", False))
        events.append(f"planner: plan written ({mode} mode, {len(plan)} steps)")
        return {"record": record.model_dump(), "plan": plan,
                "plan_mode": mode, "events": events, "evidence": [],
                "notes": list(state.get("notes", []))}

    def _add(state: State, items, label: str) -> State:
        events = list(state.get("events", []))
        ev = list(state.get("evidence", [])) + [i.model_dump(mode="json") for i in items]
        events.append(f"{label}: +{len(items)} item(s), total {len(ev)}")
        return {"evidence": ev, "events": events,
                "notes": list(state.get("notes", []))}

    def node_gather_clinvar(state: State) -> State:
        from .schema import VariantRecord
        rec = VariantRecord(**state["record"])
        return _add(state, gatherers.gather_clinvar_local(rec, ctx.data, ctx.model),
                    "gather_clinvar")

    def node_gather_gnomad(state: State) -> State:
        from .schema import VariantRecord
        rec = VariantRecord(**state["record"])
        notes = list(state.get("notes", []))
        items = gatherers.gather_gnomad(rec, state.get("live", False), notes)
        out = _add(state, items, "gather_gnomad")
        out["notes"] = notes
        return out

    def node_gather_pubmed(state: State) -> State:
        from .schema import VariantRecord
        rec = VariantRecord(**state["record"])
        notes = list(state.get("notes", []))
        items = gatherers.gather_pubmed(rec, state.get("live", False), notes)
        out = _add(state, items, "gather_pubmed")
        out["notes"] = notes
        return out

    def node_compute(state: State) -> State:
        from .schema import EvidenceItem, VariantRecord
        rec = VariantRecord(**state["record"])
        ev = [EvidenceItem(**e) for e in state["evidence"]]
        results, new_items, compute_events = compute_mod.run_analyses(
            rec, ev, ctx.data, ctx.model, llm=ctx.llm)
        events = list(state.get("events", [])) + compute_events
        counted = sum(1 for r in results if r.counts_as_evidence)
        events.append(f"compute: {counted}/{len(results)} analyses produced "
                      "evidence-grade content")
        return {"analyses": [r.model_dump(mode="json") for r in results],
                "evidence": state["evidence"]
                + [i.model_dump(mode="json") for i in new_items],
                "events": events}

    def node_judge(state: State) -> State:
        from .schema import EvidenceItem, VariantRecord
        rec = VariantRecord(**state["record"])
        ev = [EvidenceItem(**e) for e in state["evidence"]]
        j = judge_fn(rec, ev, ctx.model)
        events = list(state.get("events", []))
        events.append(f"judge: basis={j.basis} lean={j.lean} "
                      f"prob={j.model_prob_pathogenic} score={j.evidence_score}")
        return {"judgment": j.model_dump(mode="json"), "events": events}

    def node_gate(state: State) -> State:
        ev = state["evidence"]
        j = state["judgment"]
        missing = dossier_mod.missing_evidence(ev)
        if len(ev) < MIN_EVIDENCE:
            gate = GateResult(passed=False, evidence_count=len(ev),
                              min_evidence=MIN_EVIDENCE, missing=missing,
                              reason="evidence below the cite-or-decline bar")
        elif j["lean"] == "indeterminate":
            gate = GateResult(passed=False, evidence_count=len(ev),
                              min_evidence=MIN_EVIDENCE, missing=missing,
                              reason="evidence present but the judgment is "
                                     "indeterminate (no decisive lean)")
        else:
            gate = GateResult(passed=True, evidence_count=len(ev),
                              min_evidence=MIN_EVIDENCE, missing=[],
                              reason="evidence bar met and judgment decisive")
        events = list(state.get("events", []))
        events.append(f"decline_gate: {'PASS' if gate.passed else 'DECLINE'} — "
                      f"{gate.reason} ({gate.evidence_count}/{MIN_EVIDENCE} items)")
        return {"gate": gate.model_dump(mode="json"), "events": events}

    def node_reviewer(state: State) -> State:
        from .schema import (AnalysisResult, EvidenceItem, GateResult,
                             Judgment, VariantRecord)
        rec = VariantRecord(**state["record"])
        ev = [EvidenceItem(**e) for e in state["evidence"]]
        analyses = [AnalysisResult(**a) for a in state.get("analyses", [])]
        judgment = Judgment(**state["judgment"])
        gate = GateResult(**state["gate"])
        rev, new_judgment, rev_events = reviewer_mod.review(
            rec, ev, analyses, judgment, gate, llm=ctx.llm)
        events = list(state.get("events", [])) + rev_events
        return {"review": rev.model_dump(mode="json"),
                "judgment": new_judgment.model_dump(mode="json"),
                "events": events}

    def node_designer(state: State) -> State:
        from .schema import (EvidenceItem, GateResult, Judgment,
                             VariantRecord)
        rec = VariantRecord(**state["record"])
        ev = [EvidenceItem(**e) for e in state["evidence"]]
        judgment = Judgment(**state["judgment"])
        gate = GateResult(**state["gate"])
        designs, llm_note, des_events = designer_mod.design_experiments(
            rec, ev, judgment, gate, llm=ctx.llm)
        events = list(state.get("events", [])) + des_events
        return {"design": {"designs": [d.model_dump(mode="json")
                                       for d in designs],
                           "llm_note": llm_note},
                "events": events}

    def node_dossier(state: State) -> State:
        events = list(state.get("events", []))
        narrative = None
        if ctx.llm.available():
            try:
                ev_text = "\n".join(
                    f"- [{e['source']}] {e['detail']} <{e['source_id']}>"
                    for e in state["evidence"]) or "- (no evidence retrieved)"
                narrative = ctx.llm.chat(
                    "Write a 3-5 sentence narrative for a variant research "
                    "dossier using ONLY the facts below. Cite record ids in "
                    "angle brackets exactly as given. Do not add facts.\n"
                    f"Variant: {state['record']['name']}\n"
                    f"Gate passed: {state['gate']['passed']}; "
                    f"judgment lean: {state['judgment']['lean']}; "
                    f"basis: {state['judgment']['basis']}.\nEvidence:\n{ev_text}",
                    label="dossier_narrative", max_tokens=350)
                events.append("dossier: narrative written by LLM from the evidence items")
            except LLMError:
                narrative = None
        if narrative is None:
            parts = [f"Retrieved {len(state['evidence'])} independent evidence "
                     f"item(s) for {state['record']['name']}."]
            parts += [f"{e['source']}: {e['detail']} <{e['source_id']}>."
                      for e in state["evidence"]]
            parts.append("Gate outcome: "
                         + ("conclusion permitted." if state["gate"]["passed"]
                            else "DECLINED — " + dossier_mod.DECLINE_LINE + "."))
            narrative = " ".join(parts)
            events.append("dossier: narrative built by extractive template (offline mode)")
        full = dict(state)
        full["narrative"] = narrative
        full["llm_usage"] = ctx.llm.usage()
        full["events"] = events
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        md = dossier_mod.render_dossier(full)
        outputs = dossier_mod.write_outputs(full, md, Path(state["out_dir"]), stamp)
        events.append(f"dossier: wrote {outputs['dossier']} and {outputs['trace']}")
        return {"narrative": narrative, "llm_usage": full["llm_usage"],
                "outputs": outputs, "events": events}

    g = StateGraph(State)
    g.add_node("planner", node_planner)
    g.add_node("gather_clinvar", node_gather_clinvar)
    g.add_node("gather_gnomad", node_gather_gnomad)
    g.add_node("gather_pubmed", node_gather_pubmed)
    g.add_node("compute", node_compute)
    g.add_node("judge", node_judge)
    g.add_node("decline_gate", node_gate)
    g.add_node("reviewer", node_reviewer)
    g.add_node("experiment_designer", node_designer)
    g.add_node("dossier_writer", node_dossier)
    g.add_edge(START, "planner")
    g.add_edge("planner", "gather_clinvar")
    g.add_edge("gather_clinvar", "gather_gnomad")
    g.add_edge("gather_gnomad", "gather_pubmed")
    g.add_edge("gather_pubmed", "compute")
    g.add_edge("compute", "judge")
    g.add_edge("judge", "decline_gate")
    g.add_edge("decline_gate", "reviewer")
    g.add_edge("reviewer", "experiment_designer")
    g.add_edge("experiment_designer", "dossier_writer")
    g.add_edge("dossier_writer", END)
    return g.compile()


def run(query: str, out_dir: str | Path = "runs", live: bool = False,
        llm: Optional[LLMClient] = None, data: Optional[LocalData] = None) -> dict:
    ctx = _Ctx(data or LocalData(), llm or LLMClient())
    graph = build_graph(ctx)
    return graph.invoke({"query": query, "live": live,
                         "out_dir": str(out_dir), "events": [], "notes": []})
