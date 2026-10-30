"""Phase 3: reviewer critique + experiment designer.

Deterministic checks only (conftest forces VRA_OFFLINE=1; the LLM
paths are exercised with a duck-typed fake client). Guarantees under
test: the reviewer flags real conflicts, a downgrade is one step and
is recorded, a DECLINED case stays declined and gains a design, and
the reviewer NEVER upgrades.
"""
import json
from pathlib import Path

from variant_research_agent import designer as designer_mod
from variant_research_agent import reviewer as reviewer_mod
from variant_research_agent.graph import run
from variant_research_agent.schema import (AnalysisResult, Direction,
                                           EvidenceItem, GateResult,
                                           Judgment, VariantRecord)

LADDER = reviewer_mod.STRENGTH_LADDER


def _rec(**kw):
    base = dict(allele_id=1, gene="TEST", name="NM_0(TEST):c.1A>G (p.Ala1Gly)",
                sig_then="Uncertain significance")
    base.update(kw)
    return VariantRecord(**base)


def _item(source, sid, direction, detail="fact"):
    return EvidenceItem(source=source, source_id=sid, detail=detail,
                        direction=direction)


def _judgment(strength="strong", lean="pathogenic", basis="gbmr_model",
              prob=0.95):
    return Judgment(basis=basis, lean=lean, strength=strength,
                    model_prob_pathogenic=prob if basis == "gbmr_model" else None,
                    evidence_score=None if basis == "gbmr_model" else 3)


def _gate(passed=True, count=4):
    return GateResult(passed=passed, evidence_count=count, min_evidence=3,
                      missing=[], reason="test gate")


# ----------------------------------------------------------------------
# Reviewer: conflict detection + downgrade
# ----------------------------------------------------------------------
def _conflicted_case():
    ev = [
        _item("ClinVar (frozen 2024-01)", "CLINVAR:allele1",
              Direction.NEUTRAL, "VUS at freeze"),
        _item("AlphaMissense", "AM:1:1:A>G", Direction.PATHOGENIC,
              "AlphaMissense score=0.910 class=likely_pathogenic"),
        _item("gnomAD (recorded lookup, local data)", "GNOMAD:1:1:A>G",
              Direction.BENIGN, "gnomAD allele frequency = 0.031"),
    ]
    return ev


def test_reviewer_flags_conflicting_evidence():
    rev, _j, _ev = reviewer_mod.review(
        _rec(), _conflicted_case(), [], _judgment(), _gate())
    checks = {c.check: c for c in rev.critiques}
    assert "direction_conflict" in checks
    assert checks["direction_conflict"].severity == "material"
    assert "AlphaMissense" in checks["direction_conflict"].finding
    assert "gnomAD" in checks["direction_conflict"].finding


def test_downgrade_path_works_and_is_recorded():
    j_in = _judgment(strength="strong")
    rev, j_out, _ev = reviewer_mod.review(
        _rec(), _conflicted_case(), [], j_in, _gate())
    assert rev.downgraded is True
    assert rev.strength_before == "strong"
    # exactly ONE step down even with multiple material critiques
    assert rev.strength_after == "moderate"
    assert j_out.strength == "moderate"
    # lean, basis and probability are untouchable
    assert j_out.lean == j_in.lean and j_out.basis == j_in.basis
    assert j_out.model_prob_pathogenic == j_in.model_prob_pathogenic
    # the input judgment object was not mutated
    assert j_in.strength == "strong"
    assert "direction_conflict" in rev.downgrade_reason


def test_reviewer_flags_predictor_split_as_material():
    analyses = [AnalysisResult(
        name="predictor_agreement", status="ok",
        summary="Predictor agreement over 3 predictors: 1 pathogenic "
                "lean(s), 1 benign, 1 indeterminate; pairwise agreement "
                "1/3 pairs; consensus: split (no majority).",
        results={"consensus": "split (no majority)",
                 "pairwise_agreement_fraction": 0.333},
        counts_as_evidence=True, script_sha256="deadbeefcafe")]
    ev = [_item("AlphaMissense", "AM:1:1:A>G", Direction.PATHOGENIC),
          _item("REVEL (Zenodo 7072866)", "REVEL:1:1:A>G", Direction.BENIGN),
          _item("ClinVar (frozen 2024-01)", "CLINVAR:allele1", Direction.NEUTRAL)]
    rev, _j, _ev = reviewer_mod.review(_rec(), ev, analyses, _judgment(), _gate())
    checks = {c.check for c in rev.critiques if c.severity == "material"}
    assert "conflict_predictor_split" in checks


def test_reviewer_never_upgrades():
    clean = [
        _item("AlphaMissense", "AM:1:1:A>G", Direction.PATHOGENIC),
        _item("REVEL (Zenodo 7072866)", "REVEL:1:1:A>G", Direction.PATHOGENIC),
        _item("gnomAD (recorded lookup, local data)", "GNOMAD:1:1:A>G",
              Direction.BENIGN, "gnomAD allele frequency = 0.03"),
    ]
    # the gnomAD item above leans benign while the verdict leans
    # pathogenic via population family support for a benign case:
    for strength in LADDER:
        for ev, lean in ((_conflicted_case(), "pathogenic"),
                         (clean, "benign")):
            j_in = _judgment(strength=strength, lean=lean,
                             prob=0.05 if lean == "benign" else 0.95)
            rev, j_out, _ = reviewer_mod.review(_rec(), ev, [], j_in, _gate())
            assert LADDER.index(j_out.strength) <= LADDER.index(strength)
            if not rev.downgraded:
                assert j_out.strength == strength
    # a weak verdict with a supportive review stays weak
    ev_ok = [_item("AlphaMissense", "AM:1:1:A>G", Direction.PATHOGENIC),
             _item("gnomAD (recorded lookup, local data)", "GNOMAD:1:1:A>G",
                   Direction.NEUTRAL)]
    rev, j_out, _ = reviewer_mod.review(
        _rec(), ev_ok, [], _judgment(strength="weak"), _gate())
    assert j_out.strength == "weak"


class _FakeLLM:
    def available(self):
        return True

    def chat(self, prompt, label="", max_tokens=700):
        return "FAKE LLM CRITIQUE TEXT"


def test_llm_critique_is_advisory_only():
    rev_plain, j_plain, _ = reviewer_mod.review(
        _rec(), _conflicted_case(), [], _judgment(), _gate())
    rev_llm, j_llm, _ = reviewer_mod.review(
        _rec(), _conflicted_case(), [], _judgment(), _gate(), llm=_FakeLLM())
    assert rev_llm.llm_critique == "FAKE LLM CRITIQUE TEXT"
    # the deterministic outcome is identical with and without the LLM
    assert rev_llm.downgraded == rev_plain.downgraded
    assert j_llm.strength == j_plain.strength
    assert [c.check for c in rev_llm.critiques] == \
           [c.check for c in rev_plain.critiques]


# ----------------------------------------------------------------------
# Designer unit behaviour
# ----------------------------------------------------------------------
def test_designer_orders_population_first_when_missing():
    designs, _note, _ev = designer_mod.design_experiments(
        _rec(), [_item("ClinVar (frozen 2024-01)", "CLINVAR:allele1",
                       Direction.NEUTRAL)],
        _judgment(basis="evidence_scoring", prob=None), _gate(passed=False))
    assert [d.priority for d in designs] == list(range(1, len(designs) + 1))
    assert "population" in designs[0].supplies
    assert all(d.supports_pathogenic and d.supports_benign for d in designs)


def test_designer_splice_variant_gets_rna_assay():
    rec = _rec(vep_consequence="splice_region_variant")
    designs, _note, _ev = designer_mod.design_experiments(
        rec, [_item("gnomAD (recorded lookup, local data)", "GNOMAD:1:1:A>G",
                    Direction.NEUTRAL)],
        _judgment(), _gate())
    assert any("splicing" in d.assay_type for d in designs)


# ----------------------------------------------------------------------
# End-to-end on the three worked examples
# ----------------------------------------------------------------------
def test_end_to_end_arsb_downgraded_by_reviewer(tmp_path):
    state = run("ARSB:c.1178A>C", out_dir=tmp_path)
    assert state["gate"]["passed"] is True
    rev = state["review"]
    assert rev["downgraded"] is True
    assert rev["strength_before"] == "strong"
    assert rev["strength_after"] == "moderate"
    assert state["judgment"]["strength"] == "moderate"
    checks = {c["check"] for c in rev["critiques"]}
    assert "strength_thin_independent_support" in checks
    assert "independence_predictor_correlation" in checks
    assert "independence_derivative_analyses" in checks
    assert "missing_functional" in checks
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "## Reviewer critique" in md
    assert "## Validation experiment design" in md
    assert "Reviewer downgrade" in md
    trace = json.loads(Path(state["outputs"]["trace"]).read_text())
    assert trace["review"]["downgraded"] is True
    assert trace["design"]["designs"], "designs must be in the trace"
    assert trace["judgment"]["strength"] == "moderate"
    assert trace["judgment"]["model_prob_pathogenic"] > 0.98  # untouched


def test_end_to_end_nherf1_strong_stands(tmp_path):
    state = run("NHERF1:c.328C>G", out_dir=tmp_path)
    assert state["gate"]["passed"] is True
    rev = state["review"]
    assert rev["downgraded"] is False
    assert state["judgment"]["strength"] == "strong"
    assert not [c for c in rev["critiques"] if c["severity"] == "material"]
    designs = state["design"]["designs"]
    # gnomAD present -> no population design; functional leads
    assert "Functional assay" in designs[0]["assay_type"]
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "## Reviewer critique" in md
    assert "## Validation experiment design" in md
    assert "Reviewer downgrade" not in md


def test_declined_case_stays_declined_with_design(tmp_path):
    state = run("allele:28034", out_dir=tmp_path)  # RYR1 delins
    assert state["gate"]["passed"] is False
    rev = state["review"]
    assert rev["decline_upheld"] is True
    assert rev["downgraded"] is False
    # the reviewer cannot touch the judgment of a declined case either
    assert state["judgment"]["lean"] == "indeterminate"
    designs = state["design"]["designs"]
    assert len(designs) >= 3
    assert "population" in designs[0]["supplies"]
    assert any("segregation" in d["supplies"] for d in designs)
    assert all(d["supports_pathogenic"] and d["supports_benign"]
               for d in designs)
    md = Path(state["outputs"]["dossier"]).read_text()
    assert "DECLINED" in md
    assert "## Validation experiment design" in md
    assert "## Reviewer critique" in md
    trace = json.loads(Path(state["outputs"]["trace"]).read_text())
    assert trace["gate"]["passed"] is False
    assert trace["review"]["decline_upheld"] is True
    assert len(trace["design"]["designs"]) == len(designs)
