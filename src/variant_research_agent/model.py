"""Adapter for the calibrated GBM+R model from vus-evidence-agent.

Reality of the source project (checked 2026-10-30): there is NO pickled
model artifact. The adopted model — gradient boosting + REVEL features
+ isotonic calibration (MODEL_REPORT_6: AUROC 0.9705, ECE 0.0248,
Brier 0.0625 on the temporal test set) — exists as the recorded outputs
of the source project's own run in
data/processed_v2/test_predictions_trees.csv.

So this adapter loads those recorded predictions: every probability it
returns is a real output of a real model run (R4: no invented numbers).
For variants with no recorded prediction (frozen-train variants, or
anything outside the temporal test set) `predict_recorded` returns
None and the judge falls back to transparent evidence scoring.

MODEL_CARD summarises the recorded run for citation in dossiers.
"""
from __future__ import annotations

from typing import Optional

from .data import LocalData
from .schema import VariantRecord

MODEL_CARD = {
    "name": "GBM+R (gradient boosting + REVEL, isotonic calibrated)",
    "source_project": "vus-evidence-agent",
    "report": "data/processed_v2/MODEL_REPORT_6.md",
    "predictions_file": "data/processed_v2/test_predictions_trees.csv",
    "auroc": 0.9705,
    "ece": 0.0248,
    "brier": 0.0625,
    "evaluation": "temporal test set: variants reclassified after the 2024-01 freeze",
}


class CalibratedModelAdapter:
    def __init__(self, data: LocalData):
        self.data = data

    def predict_recorded(self, record: VariantRecord) -> Optional[float]:
        """The model's recorded isotonic-calibrated P(pathogenic) for
        this variant, or None when the model never scored it."""
        row = self.data.gbm_predictions().get(record.allele_id)
        if row is None:
            return None
        return row.get("prob_gbm_isotonic")

    def gene_prior(self, record: VariantRecord) -> Optional[float]:
        row = self.data.gbm_predictions().get(record.allele_id)
        return row.get("gene_prior") if row else None

    def ensemble(self, record: VariantRecord) -> Optional[dict]:
        return self.data.ensemble_predictions().get(record.allele_id)

    # ------------------------------------------------------------------
    # ADAPTER STUB — fresh inference is intentionally not implemented.
    #
    # The source project ships no serialised model, so scoring a brand
    # new variant would require retraining GBM+R on the frozen train
    # split (source: vus-evidence-agent/scripts/train_trees.py, which
    # fits on data/processed_v2/train_features.csv + train_revel.csv
    # and calibrates on a train holdout — R1 forbids touching post-
    # freeze data for this). Phase 2 work: wrap that training script
    # behind this method with a pinned seed and a persisted artifact.
    # Until then this stub raises, and callers must use the recorded
    # predictions or the evidence-scoring fallback. It must NEVER
    # return an invented probability.
    # ------------------------------------------------------------------
    def predict_fresh(self, record: VariantRecord) -> float:
        raise NotImplementedError(
            "GBM+R fresh inference is an adapter stub: the source project "
            "has no serialised model artifact. Use predict_recorded() or "
            "the evidence-scoring fallback in judge.py.")
