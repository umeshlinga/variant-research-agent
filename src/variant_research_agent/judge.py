"""The judge stage.

Primary basis: the calibrated GBM+R probability recorded by
vus-evidence-agent (see model.py). A probability from the recorded
run is a real number from a real model (R4).

Fallback basis (variants the model never scored): a transparent
evidence score — the signed sum of evidence directions
(pathogenic +1, benign -1, neutral 0). It is NOT a probability and
the dossier labels it as uncalibrated evidence scoring wherever it
is used. A lean requires |score| >= 2; anything weaker is
"indeterminate" and the decline gate will refuse to conclude.
"""
from __future__ import annotations

from .model import MODEL_CARD, CalibratedModelAdapter
from .schema import Direction, EvidenceItem, Judgment, VariantRecord


def _strength(prob: float) -> str:
    d = abs(prob - 0.5)
    return "strong" if d >= 0.4 else "moderate" if d >= 0.2 else "weak"


def judge(record: VariantRecord, evidence: list[EvidenceItem],
          model: CalibratedModelAdapter) -> Judgment:
    prob = model.predict_recorded(record)
    if prob is not None:
        lean = "pathogenic" if prob >= 0.5 else "benign"
        return Judgment(
            basis="gbmr_model",
            lean=lean,
            strength=_strength(prob),
            model_prob_pathogenic=prob,
            rationale=[
                f"GBM+R isotonic-calibrated P(pathogenic) = {prob:.3f} "
                f"({MODEL_CARD['name']}; recorded run, {MODEL_CARD['report']}: "
                f"AUROC {MODEL_CARD['auroc']}, ECE {MODEL_CARD['ece']}, "
                f"Brier {MODEL_CARD['brier']} on the temporal test set)",
            ])
    score = sum(1 if e.direction == Direction.PATHOGENIC
                else -1 if e.direction == Direction.BENIGN else 0
                for e in evidence)
    lean = ("pathogenic" if score >= 2 else
            "benign" if score <= -2 else "indeterminate")
    return Judgment(
        basis="evidence_scoring",
        lean=lean,
        strength="n/a (uncalibrated)",
        model_prob_pathogenic=None,
        evidence_score=score,
        rationale=[
            "No recorded GBM+R probability exists for this variant "
            "(adapter stub: the source project ships no serialised model), "
            "so judgment falls back to transparent evidence scoring: "
            f"signed direction sum = {score:+d} over {len(evidence)} item(s). "
            "This is NOT a calibrated probability.",
        ])
