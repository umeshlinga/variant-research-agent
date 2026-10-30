"""Pydantic schemas for the Variant Research Agent.

Design rules carried over from the source projects:
- Every evidence item carries a source identifier (BUILD_PLAN R2:
  no source, no claim). `source_id` is mandatory and non-empty.
- Only prediction-time fields exist on VariantRecord. The future
  ClinVar reclassification (sig_now / label in the source tables) is
  evaluation-only in vus-evidence-agent and is deliberately NOT
  loaded here at all (R1: temporal integrity).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Direction(str, Enum):
    PATHOGENIC = "pathogenic"
    BENIGN = "benign"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """One retrieved evidence record, cited by its source identifier."""

    source: str = Field(..., min_length=1)          # e.g. "ClinVar (frozen 2024-01)"
    source_id: str = Field(..., min_length=1)       # e.g. "CLINVAR:allele15925"
    detail: str = Field(..., min_length=1)          # human-readable fact
    direction: Direction = Direction.UNKNOWN
    live: bool = False  # True when fetched live at run time (vs local records)

    @field_validator("source_id")
    @classmethod
    def _source_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_id must not be blank (R2: no source, no claim)")
        return v


class VariantRecord(BaseModel):
    """A variant resolved against the local vus-evidence-agent data.

    All fields are prediction-time (frozen 2024-01 worldview)."""

    allele_id: int
    gene: str
    name: str                       # full ClinVar name, e.g. NM_...(GENE):c.1A>G (p.X)
    variant_type: str = ""
    chrom: str = ""
    pos: int = -1
    ref: str = ""
    alt: str = ""
    sig_then: Optional[str] = None  # ClinVar status frozen at 2024-01
    am_score: Optional[float] = None
    am_class: Optional[str] = None
    revel_score: Optional[float] = None
    gnomad_af_recorded: Optional[float] = None
    gnomad_status_recorded: Optional[str] = None  # observed | not_observed | unknown
    vep_consequence: Optional[str] = None
    dataset: str = ""               # which local table the record came from

    @property
    def genomic(self) -> str:
        return f"{self.chrom}:{self.pos}:{self.ref}>{self.alt}"

    @property
    def gnomad_variant_id(self) -> str:
        return f"{self.chrom}-{self.pos}-{self.ref}-{self.alt}"


class Judgment(BaseModel):
    basis: str                      # "gbmr_model" | "evidence_scoring"
    lean: str                       # pathogenic | benign | indeterminate
    strength: str = ""              # e.g. "strong", "moderate"
    model_prob_pathogenic: Optional[float] = None
    evidence_score: Optional[int] = None
    rationale: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    passed: bool
    evidence_count: int
    min_evidence: int
    missing: list[str] = Field(default_factory=list)
    reason: str = ""


class AnalysisResult(BaseModel):
    """One agent-authored analysis executed in the sandbox (Phase 2).

    The full script source and its captured outputs live here so the
    JSON trace is self-auditing (BUILD_PLAN Phase 2: "logs code +
    outputs into the dossier"). `counts_as_evidence` is True only when
    the script ran cleanly AND reported real computed content — a
    failed, timed-out, or empty analysis must never inflate the
    decline gate's evidence count (R3/R4).
    """

    name: str
    status: str  # ok | no_content | failed | timeout
    summary: str = ""
    results: dict = Field(default_factory=dict)
    counts_as_evidence: bool = False
    script_sha256: str = ""
    script: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    error: Optional[str] = None
    origin: str = "template"  # template | llm (script provenance)


class CritiqueItem(BaseModel):
    """One adversarial finding from the reviewer stage (Phase 3).

    `severity` is one of: "material" (can force a one-step downgrade
    of the judgment's confidence language), "notable" (a real weakness
    the reader must see), "minor" (context). Critiques are generated
    from the actual evidence items and computed analyses — never from
    outside facts (R2/R4)."""

    check: str                      # e.g. "direction_conflict"
    severity: str                   # material | notable | minor
    finding: str                    # specific, human-readable


class Review(BaseModel):
    """The reviewer stage's output (Phase 3).

    The reviewer's powers are deliberately narrow: it may downgrade
    confidence language one step (strong -> moderate -> weak) when a
    material critique exists. It may never upgrade, never change the
    lean / basis / probability, and never reverse a decline (the gate
    result is read-only input; `decline_upheld` just records that the
    reviewer found the decline consistent with the evidence state)."""

    critiques: list[CritiqueItem] = Field(default_factory=list)
    families: list[str] = Field(default_factory=list)  # effective independent families
    downgraded: bool = False
    strength_before: str = ""
    strength_after: str = ""
    downgrade_reason: str = ""
    decline_upheld: Optional[bool] = None  # True/False when the gate declined
    llm_critique: str = ""  # model-written critique, advisory only, labelled


class ExperimentDesign(BaseModel):
    """One proposed validation experiment (Phase 3 designer).

    Structured so a reader can act on it: what to run, why it fits
    this variant, and — stated before the fact — which result would
    support pathogenic and which would support benign, plus which
    missing evidence class the result would supply."""

    priority: int
    assay_type: str
    rationale: str
    supports_pathogenic: str
    supports_benign: str
    supplies: str  # the missing evidence class/item this would supply
