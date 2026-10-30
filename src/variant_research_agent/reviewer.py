"""Reviewer stage (Phase 3): adversarial critique of the draft judgment.

Sits between the decline gate and the dossier writer. The critique is
DETERMINISTIC: the same checks run offline and in LLM mode, computed
from the actual evidence items, the agent's computed analyses, the
judgment, and the gate result. When an LLM endpoint answers, a
model-written critique may be appended — clearly labelled, advisory
only, and never able to change the deterministic outcome.

Checks (the critique taxonomy):
  (a) evidence independence — items that trace to the same underlying
      source family (correlated in-silico predictors; the GBM+R
      probability, which is itself computed from REVEL + gene prior;
      agent analyses, which are computed FROM other dossier items)
      must not be read as independent confirmations.
  (b) direction conflicts — directional items leaning opposite ways,
      a frozen ClinVar record that is itself "Conflicting", a split
      predictor-agreement result, or a model lean the raw evidence
      sum contradicts.
  (c) missing evidence classes — functional, segregation, literature,
      population, or predictor classes absent for this variant.
  (d) calibration caveats — the recorded probability's coverage and
      set-level metrics; percentile context drawn from a
      reclassification-enriched reference set; an uncalibrated
      evidence-scoring judgment.
  (e) verdict strength vs support — "strong" language demands
      directional support from at least two independent evidence
      families; one correlated family is not enough.

Powers (deliberately narrow): the reviewer may DOWNGRADE the
judgment's confidence language one step (strong -> moderate ->
weak) when a MATERIAL critique exists. It may never upgrade, never
change the lean, basis, probability or evidence, and never resurrect
a DECLINED case — the gate result is read-only input here (R3).

Every number in a finding comes from the run's own data (R4); every
finding names the items it is about (R2).
"""
from __future__ import annotations

from typing import Optional

from .llm import LLMClient, LLMError
from .model import MODEL_CARD
from .schema import (AnalysisResult, CritiqueItem, Direction, EvidenceItem,
                     GateResult, Judgment, Review, VariantRecord)

STRENGTH_LADDER = ["weak", "moderate", "strong"]

# Evidence families: items in the same family trace to one underlying
# signal and must not be counted as independent confirmations.
FAMILY_PREDICTORS = "in-silico missense predictors"
FAMILY_CLINVAR = "frozen ClinVar record"
FAMILY_PRIOR = "gene prior"
FAMILY_POPULATION = "population frequency (gnomAD)"
FAMILY_LITERATURE = "literature (PubMed)"
FAMILY_ANALYSES = "agent analyses (derived)"


def _family(item: EvidenceItem) -> str:
    sid = item.source_id
    if sid.startswith("CLINVAR:"):
        return FAMILY_CLINVAR
    if sid.startswith(("AM:", "REVEL:")):
        return FAMILY_PREDICTORS
    if sid.startswith("GENEPRIOR:"):
        return FAMILY_PRIOR
    if sid.startswith("GNOMAD:"):
        return FAMILY_POPULATION
    if sid.startswith("PMID:"):
        return FAMILY_LITERATURE
    if sid.startswith("ANALYSIS:"):
        return FAMILY_ANALYSES
    return f"other ({item.source})"


def _is_analysis(item: EvidenceItem) -> bool:
    return item.source_id.startswith("ANALYSIS:")


def _gathered(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [e for e in evidence if not _is_analysis(e)]


# ----------------------------------------------------------------------
# (a) evidence independence
# ----------------------------------------------------------------------
def check_independence(record: VariantRecord, evidence: list[EvidenceItem],
                       judgment: Judgment) -> list[CritiqueItem]:
    out: list[CritiqueItem] = []
    gathered = _gathered(evidence)
    predictors = [e for e in gathered
                  if e.source_id.startswith(("AM:", "REVEL:"))]
    if len(predictors) >= 2:
        names = " and ".join(e.source for e in predictors)
        out.append(CritiqueItem(
            check="independence_predictor_correlation", severity="notable",
            finding=(f"{names} are both in-silico missense predictors "
                     "trained on overlapping variant corpora and "
                     "conservation signal — their agreement is one "
                     "correlated observation, not two independent ones.")))
    analyses_counted = [e for e in evidence if _is_analysis(e)]
    if analyses_counted:
        fams = sorted({_family(e) for e in gathered})
        out.append(CritiqueItem(
            check="independence_derivative_analyses", severity="notable",
            finding=(f"{len(analyses_counted)} of the {len(evidence)} "
                     "evidence items are agent analyses computed FROM "
                     "other items in this same dossier (population "
                     "context from the gnomAD item; agreement and "
                     "percentile statistics from the predictor items). "
                     "They add computed context, not independent "
                     "observations. Effective independent evidence "
                     f"families: {', '.join(fams)} ({len(fams)}).")))
    if judgment.basis == "gbmr_model":
        feats = [e.source for e in gathered
                 if e.source_id.startswith(("REVEL:", "GENEPRIOR:"))]
        if feats:
            out.append(CritiqueItem(
                check="independence_model_features", severity="notable",
                finding=(f"The GBM+R probability anchoring this verdict "
                         f"is itself computed from {' and '.join(feats)} "
                         f"({MODEL_CARD['report']}). Citing the "
                         "probability AND those items as separate support "
                         "double-counts one signal chain.")))
    return out


# ----------------------------------------------------------------------
# (b) direction conflicts
# ----------------------------------------------------------------------
def check_direction_conflicts(record: VariantRecord,
                              evidence: list[EvidenceItem],
                              analyses: list[AnalysisResult],
                              judgment: Judgment) -> list[CritiqueItem]:
    out: list[CritiqueItem] = []
    gathered = _gathered(evidence)
    path_items = [e for e in gathered if e.direction == Direction.PATHOGENIC]
    ben_items = [e for e in gathered if e.direction == Direction.BENIGN]
    if path_items and ben_items:
        out.append(CritiqueItem(
            check="direction_conflict", severity="material",
            finding=("Direction conflict among the gathered evidence: "
                     + "; ".join(f"{e.source} ({e.detail})" for e in path_items)
                     + " lean(s) pathogenic, while "
                     + "; ".join(f"{e.source} ({e.detail})" for e in ben_items)
                     + " lean(s) benign. No independent evidence type in "
                       "this dossier resolves the disagreement.")))
    if record.sig_then and "conflicting" in record.sig_then.lower():
        out.append(CritiqueItem(
            check="conflict_within_clinvar", severity="notable",
            finding=(f"The frozen ClinVar record itself reads "
                     f"'{record.sig_then}': submitters disagreed at the "
                     "2024-01 freeze, so the ClinVar item is neutral "
                     "context, not support for either side.")))
    for a in analyses:
        if a.name == "predictor_agreement" and a.status == "ok":
            consensus = str(a.results.get("consensus", ""))
            frac = a.results.get("pairwise_agreement_fraction")
            if consensus.startswith("split"):
                out.append(CritiqueItem(
                    check="conflict_predictor_split", severity="material",
                    finding=(f"The agent's own predictor-agreement "
                             f"analysis reports a split consensus: "
                             f"{a.summary}")))
            elif frac is not None and frac < 1.0:
                out.append(CritiqueItem(
                    check="conflict_predictor_disagreement", severity="notable",
                    finding=(f"Predictor agreement is incomplete "
                             f"(pairwise agreement fraction {frac}): "
                             f"{a.summary}")))
    if judgment.basis == "gbmr_model":
        score = sum(1 if e.direction == Direction.PATHOGENIC
                    else -1 if e.direction == Direction.BENIGN else 0
                    for e in evidence)
        fallback_lean = ("pathogenic" if score >= 2 else
                         "benign" if score <= -2 else "indeterminate")
        if fallback_lean not in ("indeterminate", judgment.lean):
            out.append(CritiqueItem(
                check="conflict_model_vs_evidence_sum", severity="material",
                finding=(f"The transparent evidence sum leans "
                         f"{fallback_lean} ({score:+d}) while the GBM+R "
                         f"probability leans {judgment.lean} "
                         f"({judgment.model_prob_pathogenic:.3f}). The "
                         "verdict follows the calibrated model, but the "
                         "raw directions disagree with it.")))
        elif fallback_lean == "indeterminate" and judgment.strength == "strong":
            out.append(CritiqueItem(
                check="conflict_model_vs_evidence_sum", severity="notable",
                finding=(f"Outside the model, the raw evidence directions "
                         f"sum to indeterminate ({score:+d}); the strong "
                         "language rests on the model probability alone.")))
    return out


# ----------------------------------------------------------------------
# (c) missing evidence classes
# ----------------------------------------------------------------------
def _has_prefix(evidence: list[EvidenceItem], *prefixes: str) -> bool:
    return any(e.source_id.startswith(prefixes) for e in evidence)


def check_missing_classes(record: VariantRecord,
                          evidence: list[EvidenceItem]) -> list[CritiqueItem]:
    classes = [
        ("functional", "missing_functional",
         _has_prefix(evidence, "FUNCTIONAL:", "ASSAY:")
         or any("functional" in e.source.lower() for e in evidence),
         "notable",
         "No functional/experimental evidence: no assay has measured "
         "what this variant does to the gene product."),
        ("segregation", "missing_segregation",
         any("segregat" in e.source.lower()
             or "family" in e.source.lower() for e in evidence),
         "notable",
         "No segregation evidence: no family data shows whether the "
         "variant tracks with disease."),
        ("population frequency", "missing_population",
         _has_prefix(evidence, "GNOMAD:"), "notable",
         "No population-frequency evidence: no successful gnomAD "
         "lookup exists for this variant, so rarity is unmeasured."),
        ("missense predictor scores", "missing_predictors",
         _has_prefix(evidence, "AM:", "REVEL:"), "notable",
         "No missense predictor scores: neither AlphaMissense nor "
         "REVEL has a score for this variant in the local data."),
        ("literature", "missing_literature",
         _has_prefix(evidence, "PMID:"), "minor",
         "No literature evidence: no published article on this exact "
         "variant is in this dossier."),
    ]
    return [CritiqueItem(check=key, severity=sev, finding=text)
            for _label, key, present, sev, text in classes if not present]


# ----------------------------------------------------------------------
# (d) calibration caveats
# ----------------------------------------------------------------------
def check_calibration(judgment: Judgment,
                      analyses: list[AnalysisResult]) -> list[CritiqueItem]:
    out: list[CritiqueItem] = []
    if judgment.basis == "gbmr_model":
        out.append(CritiqueItem(
            check="caveat_calibration_scope", severity="notable",
            finding=("The probability is a RECORDED output of the GBM+R "
                     "run, which scored 10,357 of the 27,748 temporal "
                     "test variants. Its calibration (ECE 0.0248, "
                     "AUROC 0.9705) was measured on that test set as a "
                     "whole — per-gene and per-consequence calibration "
                     "is unknown, so the probability is a set-level "
                     "calibrated estimate, not a variant-specific "
                     "guarantee.")))
    elif judgment.basis == "evidence_scoring":
        out.append(CritiqueItem(
            check="caveat_uncalibrated_judgment", severity="notable",
            finding=("No recorded GBM+R probability exists for this "
                     "variant (outside the model's recorded coverage), "
                     "so the judgment is an uncalibrated signed sum of "
                     "evidence directions — a transparency device, not "
                     "a probability.")))
    pct_ok = [a for a in analyses
              if a.name in ("population_context", "score_percentiles")
              and a.status == "ok"]
    if pct_ok:
        out.append(CritiqueItem(
            check="caveat_percentile_reference", severity="minor",
            finding=("Percentile context in this dossier is computed "
                     "against the local temporal test set, which is "
                     "enriched for variants that were later "
                     "reclassified. These are percentiles within that "
                     "enriched set, not population percentiles.")))
    return out


# ----------------------------------------------------------------------
# (e) verdict strength vs independent support
# ----------------------------------------------------------------------
def check_strength(record: VariantRecord, evidence: list[EvidenceItem],
                   judgment: Judgment, gate: GateResult) -> list[CritiqueItem]:
    if not gate.passed or judgment.basis != "gbmr_model":
        return []
    if judgment.strength not in STRENGTH_LADDER:
        return []
    support_families = sorted({
        _family(e) for e in _gathered(evidence)
        if e.direction.value == judgment.lean})
    if len(support_families) < 2:
        n = len(support_families)
        return [CritiqueItem(
            check="strength_thin_independent_support", severity="material",
            finding=(f"Strength challenge: the '{judgment.strength}' "
                     f"{judgment.lean} language rests on directional "
                     f"support from {n} independent evidence "
                     f"{'family' if n == 1 else 'families'} "
                     f"({', '.join(support_families) or 'none'}). "
                     "Correlated items count once. One family is not "
                     "enough to carry 'strong'."))]
    return []


# ----------------------------------------------------------------------
# Stage entry point
# ----------------------------------------------------------------------
def _llm_critique(llm: LLMClient, record: VariantRecord,
                  evidence: list[EvidenceItem], judgment: Judgment,
                  gate: GateResult,
                  critiques: list[CritiqueItem]) -> str:
    """Optional model-written critique. Advisory only: it is stored
    separately and can never alter the deterministic outcome."""
    try:
        ev_text = "\n".join(
            f"- [{e.source}] {e.detail} <{e.source_id}> direction={e.direction.value}"
            for e in evidence) or "- (no evidence)"
        det = "\n".join(f"- [{c.severity}] {c.check}: {c.finding}"
                        for c in critiques) or "- (none)"
        return llm.chat(
            "You are an adversarial reviewer of a variant research "
            "dossier. In at most 5 sentences, add any critique the "
            "deterministic checks below may have missed. Use ONLY the "
            "facts given; do not invent data; do not propose changing "
            "the verdict.\n"
            f"Variant: {record.name}\nGate passed: {gate.passed}; "
            f"judgment: {judgment.strength} {judgment.lean}-leaning, "
            f"basis {judgment.basis}.\nEvidence:\n{ev_text}\n"
            f"Deterministic critiques:\n{det}",
            label="reviewer_llm", max_tokens=350)
    except LLMError:
        return ""


def review(record: VariantRecord, evidence: list[EvidenceItem],
           analyses: list[AnalysisResult], judgment: Judgment,
           gate: GateResult, llm: Optional[LLMClient] = None,
           ) -> tuple[Review, Judgment, list[str]]:
    """Run the reviewer. Returns (review, possibly-downgraded judgment,
    event log lines). The input judgment is never mutated; a downgrade
    returns a copy with a weaker `strength` and identical everything
    else."""
    events: list[str] = []
    critiques: list[CritiqueItem] = []
    critiques += check_independence(record, evidence, judgment)
    critiques += check_direction_conflicts(record, evidence, analyses, judgment)
    critiques += check_missing_classes(record, evidence)
    critiques += check_calibration(judgment, analyses)
    critiques += check_strength(record, evidence, judgment, gate)

    families = sorted({_family(e) for e in _gathered(evidence)})
    rev = Review(critiques=critiques, families=families)
    out_judgment = judgment

    if not gate.passed:
        # R3 backstop: the reviewer has no path that touches the gate.
        rev.decline_upheld = True
        events.append("reviewer: case is DECLINED — reviewer cannot and "
                      "does not alter the gate outcome (R3)")
    else:
        material = [c for c in critiques if c.severity == "material"]
        if material and judgment.strength in STRENGTH_LADDER:
            idx = STRENGTH_LADDER.index(judgment.strength)
            if idx > 0:
                new_strength = STRENGTH_LADDER[idx - 1]
                rev.downgraded = True
                rev.strength_before = judgment.strength
                rev.strength_after = new_strength
                rev.downgrade_reason = (
                    "material critique(s): "
                    + ", ".join(c.check for c in material))
                out_judgment = judgment.model_copy(
                    update={"strength": new_strength})
                events.append(
                    f"reviewer: DOWNGRADE {judgment.strength} -> "
                    f"{new_strength} ({rev.downgrade_reason})")
            else:
                events.append("reviewer: material critique found but the "
                              "strength is already at the weakest band — "
                              "no downgrade possible")
    n_mat = sum(1 for c in critiques if c.severity == "material")
    events.append(f"reviewer: {len(critiques)} critique(s) "
                  f"({n_mat} material) over {len(families)} independent "
                  "evidence families")

    if llm is not None and llm.available():
        text = _llm_critique(llm, record, evidence, judgment, gate, critiques)
        if text:
            rev.llm_critique = text
            events.append("reviewer: LLM critique appended (advisory, labelled)")
    return rev, out_judgment, events
