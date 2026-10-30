"""Experiment designer stage (Phase 3).

For every case — concluded or DECLINED — propose the validation
experiment(s) that would most efficiently settle the variant. The
designer is deterministic and rule-based offline, driven only by
what the dossier actually contains: the variant's class (from the
VEP consequence and the name in the local record), the gene, and
which evidence classes are missing. Each design states, BEFORE the
fact, which result would support pathogenic and which would support
benign, and which missing evidence item it would supply — so the
proposal is falsifiable rather than decorative.

For a DECLINED case the design is the centerpiece: it converts
"insufficient evidence" into a concrete, ordered plan. For a
concluded case the designs target the evidence classes the verdict
does NOT rest on, i.e. the experiments that would independently test
it. An LLM may append advisory notes when an endpoint answers
(labelled; it never adds or removes a design).
"""
from __future__ import annotations

import re
from typing import Optional

from .llm import LLMClient, LLMError
from .schema import (EvidenceItem, ExperimentDesign, GateResult, Judgment,
                     VariantRecord)


def variant_class(record: VariantRecord) -> str:
    """Classify the variant from the annotation the local record
    carries (VEP consequence first, then name/allele patterns)."""
    cons = (record.vep_consequence or "").lower()
    name = record.name.lower()
    if "splice" in cons:
        return "splice-region"
    if "frameshift" in cons:
        return "frameshift"
    if "stop_gained" in cons or "stop_lost" in cons:
        return "stop-gain/loss"
    if "missense" in cons:
        return "missense"
    if "delins" in name:
        if len(record.ref) == len(record.alt):
            return "in-frame delins (length-preserving residue change)"
        return "delins (protein-length change)"
    if record.ref and record.alt and len(record.ref) != len(record.alt):
        return "protein-length change (indel)"
    if "del" in name or "ins" in name or "dup" in name:
        return "protein-length change (indel)"
    if len(record.ref) == 1 and len(record.alt) == 1:
        return "single-nucleotide (missense-like)"
    return "protein-altering (class limited by available annotation)"


def _has_prefix(evidence: list[EvidenceItem], *prefixes: str) -> bool:
    return any(e.source_id.startswith(prefixes) for e in evidence)


def _population_design(record: VariantRecord, vclass: str,
                       declined: bool) -> ExperimentDesign:
    return ExperimentDesign(
        priority=0,  # renumbered by caller
        assay_type="Deeper population-frequency data (current gnomAD "
                   "release + ancestry-matched control cohorts)",
        rationale=("No successful gnomAD lookup exists for this "
                   f"{vclass} variant in {record.gene}, so its rarity — "
                   "the cheapest decisive fact about a candidate "
                   "disease variant — is unmeasured. A current-release "
                   "lookup with ancestry-matched cohorts is the "
                   "fastest first step"
                   + (" to break the decline." if declined
                      else " to test the verdict's rarity assumption.")),
        supports_pathogenic=("The variant remains absent, or orders of "
                             "magnitude rarer than known benign "
                             "polymorphisms, in ancestry-matched "
                             "controls at a scale where a neutral "
                             "variant would be expected to appear."),
        supports_benign=("An allele frequency comparable to known "
                         "benign polymorphisms — far too common for a "
                         "penetrant disease allele in this gene — in "
                         "any well-sampled ancestry group."),
        supplies="the missing population-frequency evidence "
                 "(a successful gnomAD-scale lookup)")


def _functional_design(record: VariantRecord, vclass: str,
                       declined: bool) -> ExperimentDesign:
    gene = record.gene
    if vclass == "splice-region":
        return ExperimentDesign(
            priority=0,
            assay_type="RNA/splicing assay (minigene splicing assay, or "
                       "RT-PCR of patient RNA where a sample exists)",
            rationale=(f"This is a splice-region variant in {gene}; "
                       "the decisive unknown is what it does to the "
                       "transcript. A splicing assay reads that out "
                       "directly, and no functional evidence of any "
                       "kind is in this dossier."),
            supports_pathogenic=("An aberrant transcript at appreciable "
                                 "fraction: exon skipping, intron "
                                 "retention, or a frameshifted / "
                                 "premature-termination product, "
                                 "absent from wild-type controls."),
            supports_benign=("Only normally spliced transcript, "
                             "indistinguishable from the wild-type "
                             "control across replicates."),
            supplies="functional evidence (RNA-level), a class "
                     "entirely absent from this dossier")
    article = "an" if vclass[0] in "aeiou" else "a"
    return ExperimentDesign(
        priority=0,
        assay_type=f"Functional assay of the {gene} gene product "
                   "(cellular model expressing variant vs wild-type)",
        rationale=(f"This is {article} {vclass} variant in {gene}; the "
                   "decisive unknown is what the change does to the "
                   "gene product's activity, stability, or interaction "
                   "behaviour. A controlled variant-vs-wild-type assay "
                   "measures exactly that, and no functional evidence "
                   "of any kind is in this dossier."),
        supports_pathogenic=("Variant protein activity, stability, or "
                             "localisation significantly outside the "
                             "wild-type range across replicates, in "
                             "the direction of the gene's known "
                             "disease mechanism."),
        supports_benign=("Variant protein measures within the "
                         "wild-type range across replicates on every "
                         "readout."),
        supplies="functional evidence, a class entirely absent from "
                 "this dossier")


def _segregation_design(record: VariantRecord, vclass: str,
                        declined: bool) -> ExperimentDesign:
    return ExperimentDesign(
        priority=0,
        assay_type="Segregation analysis (genotype affected and "
                   "unaffected relatives)",
        rationale=("No family data exists for this variant. "
                   "Co-segregation is evidence of a different KIND "
                   "from every predictor and frequency item in this "
                   "dossier — it observes the variant in patients, "
                   "not in a model — so it adds a genuinely "
                   "independent observation."),
        supports_pathogenic=("The variant co-segregates with the "
                             "phenotype: present in affected relatives "
                             "and absent from unaffected relatives, "
                             "consistent with the gene's inheritance "
                             "model."),
        supports_benign=("Non-segregation: an affected relative who "
                         "does not carry the variant, or unaffected "
                         "carriers at a rate the inheritance model "
                         "cannot accommodate."),
        supplies="segregation evidence, a class entirely absent from "
                 "this dossier")


def _case_design(record: VariantRecord, vclass: str,
                 declined: bool) -> ExperimentDesign:
    return ExperimentDesign(
        priority=0,
        assay_type="Case aggregation (published case series, ClinVar "
                   "submitter detail, matchmaking exchange)",
        rationale=("No published case data on this exact variant is "
                   "in the dossier. Aggregating independent probands "
                   "converts an anecdote into a countable observation "
                   "and is often what moves a VUS re-review."),
        supports_pathogenic=("Multiple unrelated affected probands "
                             "carry the variant with a consistent "
                             "phenotype, while it stays absent from "
                             "control cohorts."),
        supports_benign=("Reports of the variant in unaffected "
                         "individuals, or in probands whose phenotype "
                         "is fully explained by another cause."),
        supplies="literature evidence (published data on this exact "
                 "variant)")


def design_experiments(record: VariantRecord, evidence: list[EvidenceItem],
                       judgment: Judgment, gate: GateResult,
                       llm: Optional[LLMClient] = None,
                       ) -> tuple[list[ExperimentDesign], str, list[str]]:
    """Propose the ordered designs. Returns (designs, llm_note, events).

    Order is by expected information per unit effort given what is
    missing: an unmeasured population frequency first (cheap and
    often decisive), then the functional readout matched to the
    variant class, then segregation, then case aggregation."""
    events: list[str] = []
    vclass = variant_class(record)
    declined = not gate.passed
    designs: list[ExperimentDesign] = []
    if not _has_prefix(evidence, "GNOMAD:"):
        designs.append(_population_design(record, vclass, declined))
    designs.append(_functional_design(record, vclass, declined))
    designs.append(_segregation_design(record, vclass, declined))
    if not _has_prefix(evidence, "PMID:"):
        designs.append(_case_design(record, vclass, declined))
    for i, d in enumerate(designs, 1):
        d.priority = i
    events.append(f"designer: {len(designs)} experiment design(s) for a "
                  f"{vclass} variant in {record.gene}"
                  + (" (DECLINED case — design is the deliverable)"
                     if declined else ""))

    llm_note = ""
    if llm is not None and llm.available():
        try:
            listed = "; ".join(f"{d.priority}. {d.assay_type}"
                                for d in designs)
            llm_note = llm.chat(
                "In at most 3 sentences, note any practical "
                "consideration for running these proposed validation "
                "experiments for a genetic variant. Do not add or "
                "remove experiments and do not invent results.\n"
                f"Variant: {record.name} (class: {vclass}). "
                f"Proposed: {listed}",
                label="designer_llm", max_tokens=250)
            if llm_note:
                events.append("designer: LLM note appended (advisory, labelled)")
        except LLMError:
            llm_note = ""
    return designs, llm_note, events
