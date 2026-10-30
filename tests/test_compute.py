"""Compute stage (Phase 2): analyses produce real computed evidence;
failed / empty analyses never inflate the evidence count."""
import json
from pathlib import Path

import pytest

from variant_research_agent import compute as compute_mod
from variant_research_agent import gatherers
from variant_research_agent.data import LocalData
from variant_research_agent.graph import run
from variant_research_agent.model import CalibratedModelAdapter
from variant_research_agent.schema import AnalysisResult


def _result(status, counts):
    return AnalysisResult(name="toy", status=status, summary="s",
                          results={"x": 1} if counts else {},
                          counts_as_evidence=counts,
                          script_sha256="abc123def456")


def test_analysis_to_evidence_only_for_real_content():
    item = compute_mod.analysis_to_evidence(_result("ok", True))
    assert item is not None
    assert item.source_id == "ANALYSIS:toy:abc123def456"
    for status in ("failed", "timeout", "no_content"):
        assert compute_mod.analysis_to_evidence(_result(status, False)) is None


def _arsb():
    data = LocalData()
    rec = data.resolve("ARSB:c.1178A>C")
    assert rec is not None
    model = CalibratedModelAdapter(data)
    notes: list[str] = []
    ev = gatherers.gather_clinvar_local(rec, data, model)
    ev += gatherers.gather_gnomad(rec, False, notes)
    return rec, ev, data, model


def test_prepare_inputs_uses_real_data():
    rec, ev, data, model = _arsb()
    pop = compute_mod.prepare_inputs("population_context", rec, ev, data, model)
    assert pop["af"] == pytest.approx(7.663e-05)
    assert len(pop["reference_af"]) > 10_000  # real test-set AFs
    pred = compute_mod.prepare_inputs("predictor_agreement", rec, ev, data, model)
    assert pred["gene_prior"] == pytest.approx(0.8189, abs=1e-3)
    pct = compute_mod.prepare_inputs("score_percentiles", rec, ev, data, model)
    assert len(pct["reference"]["am_score"]) > 10_000
    assert len(pct["reference"]["revel_score"]) > 10_000


def test_run_analyses_arsb_all_count():
    rec, ev, data, model = _arsb()
    results, items, _events = compute_mod.run_analyses(rec, ev, data, model)
    assert [r.name for r in results] == compute_mod.ANALYSIS_ORDER
    assert all(r.status == "ok" for r in results)
    assert len(items) == 3
    by_name = {r.name: r for r in results}
    pop = by_name["population_context"].results
    assert pop["reference_n"] > 10_000
    assert pop["rarity_class"].startswith("rare")
    agr = by_name["predictor_agreement"].results
    assert agr["consensus"] == "pathogenic (unanimous)"
    assert agr["pairwise_agreement_fraction"] == 1.0
    pct = by_name["score_percentiles"].results
    # REVEL 0.906 sits at ~the 83rd percentile of this test set (the
    # set is enriched for high scores — it is variants that were
    # reclassified). The computed value is asserted, not assumed.
    assert pct["revel_score_percentile_in_local_test_set"] > 75


def test_run_analyses_thin_variant_no_content():
    data = LocalData()
    rec = data.resolve("allele:28034")  # RYR1 delins: no scores, no AF
    assert rec is not None
    model = CalibratedModelAdapter(data)
    ev = gatherers.gather_clinvar_local(rec, data, model)
    results, items, _events = compute_mod.run_analyses(rec, ev, data, model)
    assert items == []  # nothing real to compute -> nothing counted
    assert all(r.status == "no_content" for r in results)
    assert all(not r.counts_as_evidence for r in results)


def test_failed_analysis_does_not_inflate_evidence(monkeypatch):
    rec, ev, data, model = _arsb()
    monkeypatch.setitem(compute_mod.TEMPLATES, "population_context",
                         "raise RuntimeError('deliberate test failure')\n")
    results, items, _events = compute_mod.run_analyses(rec, ev, data, model)
    by_name = {r.name: r for r in results}
    assert by_name["population_context"].status == "failed"
    assert by_name["population_context"].counts_as_evidence is False
    assert len(items) == 2  # only the two surviving analyses count


def test_end_to_end_arsb_has_analyses_section(tmp_path):
    state = run("ARSB:c.1178A>C", out_dir=tmp_path)
    analyses = state["analyses"]
    assert len(analyses) == 3
    assert all(a["status"] == "ok" for a in analyses)
    # 5 gathered items (Phase 1) + 3 analysis items, all counted once
    assert state["gate"]["evidence_count"] == len(state["evidence"]) == 8
    assert state["gate"]["passed"] is True
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "## Analyses run by the agent" in md
    assert "ANALYSIS:population_context:" in md
    trace = json.loads(Path(state["outputs"]["trace"]).read_text())
    assert len(trace["analyses"]) == 3
    pop = next(a for a in trace["analyses"] if a["name"] == "population_context")
    assert "af_percentile_in_local_test_set" in pop["results"]
    assert "population_context" in pop["script"]  # source kept in trace
    assert pop["script_sha256"]


def test_end_to_end_ryr1_still_declines(tmp_path):
    state = run("allele:28034", out_dir=tmp_path)
    assert state["gate"]["passed"] is False
    # analyses ran but had nothing to compute: count stays at the
    # single frozen ClinVar item — no inflation from empty analyses
    assert state["gate"]["evidence_count"] == 1
    assert all(a["status"] == "no_content" for a in state["analyses"])
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "## Analyses run by the agent" in md
    assert "DECLINED" in md
