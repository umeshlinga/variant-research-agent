"""Decline gate behaviour (R3): fewer than 3 independent evidence
items declines; an indeterminate judgment declines even with enough
items; a decisive judgment with >= 3 items passes."""
from variant_research_agent.data import LocalData
from variant_research_agent.graph import build_graph, _Ctx
from variant_research_agent.llm import LLMClient
from variant_research_agent.schema import Direction, EvidenceItem
from variant_research_agent import judge as judge_mod
from variant_research_agent.model import CalibratedModelAdapter


def _item(source, direction=Direction.NEUTRAL):
    return EvidenceItem(source=source, source_id=f"{source}:1",
                        detail="fact", direction=direction)


def test_evidence_scoring_declines_when_thin():
    """Judge-level: 2 items can still lean, but the gate (next test)
    is what refuses. Here: 1 pathogenic + 1 benign = indeterminate."""
    rec_items = [_item("A", Direction.PATHOGENIC), _item("B", Direction.BENIGN)]
    data = LocalData()
    model = CalibratedModelAdapter(data)
    from variant_research_agent.schema import VariantRecord
    rec = VariantRecord(allele_id=-1, gene="TEST", name="TEST:c.1A>G")
    j = judge_mod.judge(rec, rec_items, model)
    assert j.basis == "evidence_scoring"
    assert j.lean == "indeterminate"


def _run_with_stubbed_gatherers(monkeypatch, tmp_path, n_items, lean_prob=None):
    """Drive the real graph but stub the gatherers + model so the gate
    sees exactly n_items evidence items."""
    import variant_research_agent.graph as graph_mod
    import variant_research_agent.gatherers as g
    import variant_research_agent.compute as compute_mod

    items = [_item(f"S{i}", Direction.PATHOGENIC if lean_prob else Direction.NEUTRAL)
             for i in range(n_items)]
    monkeypatch.setattr(g, "gather_clinvar_local", lambda r, d, m: items)
    monkeypatch.setattr(g, "gather_gnomad", lambda r, live, notes: [])
    monkeypatch.setattr(g, "gather_pubmed", lambda r, live, notes: [])
    # Phase 2: stub the compute stage too, so the gate sees exactly
    # n_items — these tests isolate gate behaviour, not the analyses.
    monkeypatch.setattr(compute_mod, "run_analyses",
                        lambda *a, **k: ([], [], []))

    class FakeModel:
        def predict_recorded(self, rec):
            return lean_prob
        def ensemble(self, rec):
            return None

    import variant_research_agent.judge as jm
    real_judge = jm.judge
    monkeypatch.setattr(jm, "judge",
                        lambda rec, ev, model: real_judge(rec, ev, FakeModel()))
    monkeypatch.setattr(graph_mod, "judge_fn",
                        lambda rec, ev, model: real_judge(rec, ev, FakeModel()))

    ctx = _Ctx(LocalData(), LLMClient())
    graph = build_graph(ctx)
    return graph.invoke({"query": "allele:15925", "live": False,
                         "out_dir": str(tmp_path), "events": [], "notes": []})


def test_gate_declines_with_two_items(monkeypatch, tmp_path):
    state = _run_with_stubbed_gatherers(monkeypatch, tmp_path, 2, lean_prob=0.99)
    assert state["gate"]["passed"] is False
    assert state["gate"]["evidence_count"] == 2
    assert "below the cite-or-decline bar" in state["gate"]["reason"]


def test_gate_passes_with_three_items_and_model_prob(monkeypatch, tmp_path):
    state = _run_with_stubbed_gatherers(monkeypatch, tmp_path, 3, lean_prob=0.99)
    assert state["gate"]["passed"] is True
    assert state["judgment"]["basis"] == "gbmr_model"
    assert state["judgment"]["lean"] == "pathogenic"
