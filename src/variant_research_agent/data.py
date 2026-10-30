"""Local data access over the vus-evidence-agent processed tables.

The ClinVar gatherer's source of truth is the LOCAL processed data of
~/workspace/vus-evidence-agent (no scraping, per the Phase 1 spec):

  data/processed_v3/test_features.csv        richest test-set table
  data/processed_v2/test_features.csv        same test set, fewer columns
  data/processed_v2/test_predictions_trees.csv   GBM+R recorded outputs
  data/processed_v3/test_predictions_ensemble.csv  tranche ensemble outputs
  data/processed_v2/train_features.csv       frozen train set (fallback)

Only prediction-time columns are read. sig_now / label exist in the
source tables for evaluation only and are never loaded (R1).
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Optional

from .schema import VariantRecord

DEFAULT_VUS_HOME = Path.home() / "workspace" / "vus-evidence-agent"

# columns we are willing to read from any source table (prediction-time only)
_KEEP = {
    "allele_id", "gene", "name", "type", "chrom", "pos", "ref", "alt",
    "sig_then", "significance", "am_score", "am_class", "revel_score",
    "gnomad_af", "gnomad_status", "vep_consequence",
}


def vus_home() -> Path:
    return Path(os.environ.get("VRA_VUS_HOME", str(DEFAULT_VUS_HOME)))


def _float(x) -> Optional[float]:
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _row_to_record(row: dict, dataset: str) -> VariantRecord:
    return VariantRecord(
        allele_id=int(row["allele_id"]),
        gene=row.get("gene", ""),
        name=row.get("name", ""),
        variant_type=row.get("type", ""),
        chrom=str(row.get("chrom", "")),
        pos=int(row["pos"]) if str(row.get("pos", "")).lstrip("-").isdigit() else -1,
        ref=row.get("ref", ""),
        alt=row.get("alt", ""),
        sig_then=row.get("sig_then") or row.get("significance") or None,
        am_score=_float(row.get("am_score")),
        am_class=row.get("am_class") or None,
        revel_score=_float(row.get("revel_score")),
        gnomad_af_recorded=_float(row.get("gnomad_af")),
        gnomad_status_recorded=row.get("gnomad_status") or None,
        vep_consequence=row.get("vep_consequence") or None,
        dataset=dataset,
    )


class LocalData:
    """Lazy, cached access to the source project's processed tables."""

    def __init__(self, home: Optional[Path] = None):
        self.home = home or vus_home()
        self._tables: dict[str, list[dict]] = {}
        self._gbmr: Optional[dict[int, dict]] = None
        self._ensemble: Optional[dict[int, dict]] = None

    # -- raw table loading -------------------------------------------------
    def _load(self, relpath: str) -> list[dict]:
        if relpath not in self._tables:
            path = self.home / relpath
            rows: list[dict] = []
            if path.exists():
                with open(path, newline="") as f:
                    for raw in csv.DictReader(f):
                        rows.append({k: v for k, v in raw.items() if k in _KEEP})
            self._tables[relpath] = rows
        return self._tables[relpath]

    def gbm_predictions(self) -> dict[int, dict]:
        """Recorded outputs of the adopted GBM+R model (isotonic calibrated).

        Source: data/processed_v2/test_predictions_trees.csv, produced by
        the source project's scripts/train_trees.py run (MODEL_REPORT_6:
        AUROC 0.9705, ECE 0.0248, Brier 0.0625 on the temporal test set).
        """
        if self._gbmr is None:
            self._gbmr = {}
            path = self.home / "data/processed_v2/test_predictions_trees.csv"
            if path.exists():
                with open(path, newline="") as f:
                    for raw in csv.DictReader(f):
                        self._gbmr[int(raw["allele_id"])] = {
                            "prob_gbm_isotonic": _float(raw.get("prob_gbm_isotonic")),
                            "prob_gbm_raw": _float(raw.get("prob_gbm_raw")),
                            "gene_prior": _float(raw.get("gene_prior")),
                        }
        return self._gbmr

    def ensemble_predictions(self) -> dict[int, dict]:
        if self._ensemble is None:
            self._ensemble = {}
            path = self.home / "data/processed_v3/test_predictions_ensemble.csv"
            if path.exists():
                with open(path, newline="") as f:
                    for raw in csv.DictReader(f):
                        self._ensemble[int(raw["allele_id"])] = {
                            "prob_ensemble": _float(raw.get("prob_ensemble")),
                            "tranche": raw.get("tranche", ""),
                        }
        return self._ensemble

    # -- reference distributions (Phase 2 compute stage) --------------------
    _TEST_TABLES = [
        "data/processed_v3/test_features.csv",
        "data/processed_v2/test_features.csv",
    ]

    def test_rows(self) -> list[dict]:
        """Rows of the richest available temporal test-features table
        (v3 preferred, v2 fallback). Prediction-time columns only —
        the _KEEP whitelist in _load already excludes sig_now/label (R1)."""
        for relpath in self._TEST_TABLES:
            rows = self._load(relpath)
            if rows:
                return rows
        return []

    def column_distribution(self, column: str) -> list[float]:
        """All non-null values of a numeric column across the test set,
        e.g. the recorded gnomAD AFs or the AlphaMissense scores. Used
        by the Phase 2 analyses as the reference distribution for
        percentile context — every value is a real local datum (R4)."""
        out: list[float] = []
        for row in self.test_rows():
            v = _float(row.get(column))
            if v is not None:
                out.append(v)
        return out

    def gene_prior_distribution(self) -> list[float]:
        """Gene-prior values across the variants the GBM+R run scored."""
        out: list[float] = []
        for row in self.gbm_predictions().values():
            v = row.get("gene_prior")
            if v is not None:
                out.append(v)
        return out

    # -- variant resolution --------------------------------------------------
    _TABLE_ORDER = [
        ("data/processed_v3/test_features.csv", "processed_v3/test_features"),
        ("data/processed_v2/test_features.csv", "processed_v2/test_features"),
        ("data/processed_v2/train_features.csv", "processed_v2/train_features"),
    ]

    def resolve(self, query: str) -> Optional[VariantRecord]:
        """Resolve a user query against the local tables.

        Accepted forms:
          "15925" or "allele:15925"          ClinVar allele id
          "5:78839391:T>G"                   genomic (GRCh38, as in source data)
          "ARSB:c.1178A>C"                   gene + c. change
          any substring of the ClinVar name  e.g. "c.1444C>T"
        """
        q = query.strip()
        m = re.fullmatch(r"(?:allele:)?(\d+)", q)
        if m:
            return self._find(lambda r: r["allele_id"] == m.group(1))
        m = re.fullmatch(r"(?:chr)?([\dXYM]+):(\d+):([A-Za-z]+)>([A-Za-z]+)", q)
        if m:
            chrom, pos, ref, alt = m.groups()
            return self._find(
                lambda r: (str(r.get("chrom")) == chrom and str(r.get("pos")) == pos
                           and r.get("ref") == ref and r.get("alt") == alt))
        m = re.fullmatch(r"([A-Za-z0-9\-]+)[:\s]+(c\.\S+)", q)
        if m:
            gene, change = m.group(1).upper(), m.group(2)
            return self._find(
                lambda r: r.get("gene", "").upper() == gene and change in r.get("name", ""))
        return self._find(lambda r: q.lower() in r.get("name", "").lower())

    def _find(self, pred) -> Optional[VariantRecord]:
        for relpath, dataset in self._TABLE_ORDER:
            for row in self._load(relpath):
                if pred(row):
                    return _row_to_record(row, dataset)
        return None
