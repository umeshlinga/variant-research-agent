"""Evidence gatherers. Each returns structured EvidenceItems with
source identifiers (R2). Patterns ported from vus-evidence-agent's
build_v3 evidence logic (scripts/run_agent_real.py):

- REVEL is its own cited item (public Zenodo record 7072866).
- A gnomAD item exists only when a lookup actually happened: an AF
  value, or a retrieved "not observed" record. An unknown lookup
  yields NO item — absence of a lookup is not evidence of absence.
- The frozen ClinVar status is always exactly one item.
- sig_now / label (the future reclassification) are NEVER evidence.
"""
from __future__ import annotations

import re
from typing import Optional

import requests

from .data import LocalData
from .model import CalibratedModelAdapter
from .schema import Direction, EvidenceItem, VariantRecord

GNOMAD_API = "https://gnomad.broadinstitute.org/api"
PUBMED_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ----------------------------------------------------------------------
# (a) ClinVar + precomputed predictors, from the LOCAL processed data
# ----------------------------------------------------------------------
def _clinvar_direction(sig_then: Optional[str]) -> Direction:
    s = (sig_then or "").lower()
    if "pathogenic" in s and "benign" not in s and "conflicting" not in s:
        return Direction.PATHOGENIC
    if "benign" in s and "pathogenic" not in s:
        return Direction.BENIGN
    return Direction.NEUTRAL


def gather_clinvar_local(record: VariantRecord, data: LocalData,
                         model: CalibratedModelAdapter) -> list[EvidenceItem]:
    """ClinVar frozen status + AlphaMissense + REVEL + gene prior,
    all from the local processed tables (no scraping)."""
    ev: list[EvidenceItem] = [EvidenceItem(
        source="ClinVar (frozen 2024-01)",
        source_id=f"CLINVAR:allele{record.allele_id}",
        detail=f"ClinVar status at the 2024-01 freeze: {record.sig_then or 'not recorded'}",
        direction=_clinvar_direction(record.sig_then),
    )]
    if record.am_score is not None:
        d = (Direction.PATHOGENIC if record.am_class == "likely_pathogenic"
             else Direction.BENIGN if record.am_class == "likely_benign"
             else Direction.NEUTRAL)
        ev.append(EvidenceItem(
            source="AlphaMissense",
            source_id=f"AM:{record.genomic}",
            detail=f"AlphaMissense score={record.am_score:.3f} class={record.am_class}",
            direction=d))
    if record.revel_score is not None:
        # Pejaver et al. 2022 REVEL thresholds: >=0.644 PP3-supporting,
        # <=0.290 BP4-supporting; between them, no directional claim.
        d = (Direction.PATHOGENIC if record.revel_score >= 0.644
             else Direction.BENIGN if record.revel_score <= 0.290
             else Direction.NEUTRAL)
        ev.append(EvidenceItem(
            source="REVEL (Zenodo 7072866)",
            source_id=f"REVEL:{record.genomic}",
            detail=f"REVEL score={record.revel_score:.3f}",
            direction=d))
    ens = model.ensemble(record)
    if ens and ens.get("prob_ensemble") is not None:
        ev.append(EvidenceItem(
            source="Gene prior (frozen train)",
            source_id=f"GENEPRIOR:{record.gene}:frozen2024",
            detail=f"gene={record.gene} tranche={ens.get('tranche', '')} "
                   f"(prior from frozen train labels only)",
            direction=Direction.NEUTRAL))
    return ev


# ----------------------------------------------------------------------
# (b) gnomAD — live GraphQL API, with the recorded lookup as fallback
# ----------------------------------------------------------------------
_GNOMAD_QUERY = """
query($variantId: String!, $dataset: DatasetId!) {
  variant(variantId: $variantId, dataset: $dataset) {
    genome { af }
    exome { af }
  }
}"""


def fetch_gnomad_live(record: VariantRecord, timeout: float = 20.0) -> Optional[EvidenceItem]:
    """Live gnomAD GraphQL lookup (gnomad_r4). Returns None on any
    failure — the caller logs it and falls back to the recorded item."""
    if record.pos < 0 or not record.ref or not record.alt:
        return None
    try:
        r = requests.post(GNOMAD_API, json={
            "query": _GNOMAD_QUERY,
            "variables": {"variantId": record.gnomad_variant_id, "dataset": "gnomad_r4"},
        }, timeout=timeout)
        r.raise_for_status()
        variant = (r.json().get("data") or {}).get("variant")
    except (requests.RequestException, ValueError):
        return None
    if not variant:
        return EvidenceItem(
            source="gnomAD (live GraphQL, gnomad_r4)",
            source_id=f"GNOMAD:{record.genomic}",
            detail="not observed in gnomAD v4 (live lookup returned no variant record)",
            direction=Direction.NEUTRAL, live=True)
    afs = [p["af"] for p in (variant.get("genome"), variant.get("exome"))
           if p and p.get("af") is not None]
    if not afs:
        return None
    af = max(afs)
    return EvidenceItem(
        source="gnomAD (live GraphQL, gnomad_r4)",
        source_id=f"GNOMAD:{record.genomic}",
        detail=f"gnomAD v4 allele frequency (max of genome/exome) = {af:.3g}",
        direction=Direction.BENIGN if af >= 0.01 else Direction.NEUTRAL,
        live=True)


def gather_gnomad(record: VariantRecord, live: bool,
                  notes: list[str]) -> list[EvidenceItem]:
    if live:
        item = fetch_gnomad_live(record)
        if item is not None:
            return [item]
        notes.append("gnomAD live lookup failed or returned no frequency; "
                     "fell back to the recorded lookup from the local data")
    status = record.gnomad_status_recorded
    if status == "observed" and record.gnomad_af_recorded is not None:
        af = record.gnomad_af_recorded
        return [EvidenceItem(
            source="gnomAD (recorded lookup, local data)",
            source_id=f"GNOMAD:{record.genomic}",
            detail=f"gnomAD allele frequency = {af:.3g}",
            direction=Direction.BENIGN if af >= 0.01 else Direction.NEUTRAL)]
    if status == "not_observed":
        return [EvidenceItem(
            source="gnomAD (recorded lookup, local data)",
            source_id=f"GNOMAD:{record.genomic}",
            detail="not observed in gnomAD (recorded lookup returned no "
                   "frequency for this allele)",
            direction=Direction.NEUTRAL)]
    notes.append("gnomAD: no successful lookup recorded for this allele "
                 "(status unknown) — no gnomAD evidence item")
    return []


# ----------------------------------------------------------------------
# (c) Literature — PubMed E-utilities (live only; offline returns none)
# ----------------------------------------------------------------------
def _protein_change(name: str) -> Optional[str]:
    m = re.search(r"\(p\.([A-Za-z]+[0-9]+[A-Za-z]+)\)", name)
    return m.group(1) if m else None


def fetch_pubmed_live(record: VariantRecord, retmax: int = 5,
                      timeout: float = 20.0) -> list[EvidenceItem]:
    """E-utilities esearch + esummary for gene + protein change.
    Existence of literature is context, not direction — items are
    NEUTRAL by design. Returns [] on any failure."""
    change = _protein_change(record.name)
    term = f"{record.gene}[Gene] AND {change}" if change else f"{record.gene}[Gene] AND variant"
    try:
        r = requests.get(f"{PUBMED_EUTILS}/esearch.fcgi", params={
            "db": "pubmed", "term": term, "retmax": retmax, "retmode": "json",
            "tool": "variant-research-agent"}, timeout=timeout)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        r = requests.get(f"{PUBMED_EUTILS}/esummary.fcgi", params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "json",
            "tool": "variant-research-agent"}, timeout=timeout)
        r.raise_for_status()
        result = r.json().get("result", {})
    except (requests.RequestException, ValueError):
        return []
    items = []
    for pmid in ids:
        doc = result.get(pmid) or {}
        title = doc.get("title") or "(untitled)"
        year = (doc.get("pubdate") or "")[:4]
        items.append(EvidenceItem(
            source="PubMed (live E-utilities)",
            source_id=f"PMID:{pmid}",
            detail=f"{title} ({year})" if year else title,
            direction=Direction.NEUTRAL, live=True))
    return items


def gather_pubmed(record: VariantRecord, live: bool,
                  notes: list[str]) -> list[EvidenceItem]:
    if not live:
        notes.append("PubMed not queried (offline mode) — literature "
                     "evidence not counted in this run")
        return []
    items = fetch_pubmed_live(record)
    if not items:
        notes.append("PubMed live query returned no articles for this variant")
    return items
