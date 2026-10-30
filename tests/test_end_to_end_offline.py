"""End-to-end offline runs on real variants from the local data.
No network, no LLM (conftest forces VRA_OFFLINE=1)."""
import json
from pathlib import Path

from variant_research_agent.graph import run


def test_benign_variant_end_to_end(tmp_path):
    state = run("NHERF1:c.328C>G", out_dir=tmp_path)
    assert state["gate"]["passed"] is True
    assert state["judgment"]["basis"] == "gbmr_model"
    assert state["judgment"]["lean"] == "benign"
    assert state["judgment"]["model_prob_pathogenic"] is not None
    assert state["judgment"]["model_prob_pathogenic"] < 0.05
    assert len(state["evidence"]) >= 3
    assert all(e["source_id"] for e in state["evidence"])
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "Evidence summary" in md and "benign" in md
    trace = json.loads(Path(state["outputs"]["trace"]).read_text())
    assert trace["llm_usage"]["mode"] == "offline"
    assert trace["gate"]["passed"] is True


def test_thin_variant_declines_end_to_end(tmp_path):
    # RYR1 delins: VUS at the freeze, no predictor scores, no gnomAD
    # lookup recorded -> only the frozen ClinVar item exists.
    state = run("allele:28034", out_dir=tmp_path)
    assert state["gate"]["passed"] is False
    assert state["gate"]["evidence_count"] < 3
    assert state["gate"]["missing"], "a decline must name missing evidence (R3)"
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "DECLINED" in md
    assert "insufficient evidence — remains VUS" in md


def test_unresolvable_variant_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="not found"):
        run("NOTAGENE:c.1A>G", out_dir=tmp_path)
