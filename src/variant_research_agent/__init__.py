"""Variant Research Agent — Phase 1 (fusion).

LangGraph pipeline: planner -> gatherers (ClinVar local, gnomAD,
PubMed) -> judge (calibrated GBM+R) -> decline gate -> dossier.
See BUILD_PLAN.md for the rules (R1-R5) this package enforces.
"""
