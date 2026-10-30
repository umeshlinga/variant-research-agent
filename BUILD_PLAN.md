# Variant Research Agent - Build Plan
Owner: Umesh Linga. Started 2026-10-30. Capstone build fusing his three
flagship projects into one autonomous research system.

## What it is
An autonomous research agent for human genetic variants. Input: a variant
(HGVS / VCF-style / gene+change). Output: an auditable research dossier.
Loop: PLAN -> GATHER -> COMPUTE -> JUDGE -> CRITIQUE -> DESIGN (validation
experiment) -> DOSSIER. LLMs drive every stage; the calibrated GBM+R model
from vus-evidence-agent is the quantitative anchor; the system DECLINES to
conclude when evidence is below the bar (fewer than 3 independent evidence
items), exactly the Omevra cite-or-decline rule.

## Source modules (reuse, do not rebuild)
- ~/workspace/vus-evidence-agent (package src/vus_agent): ClinVar temporal
  split data (data/processed*), calibrated model GBM+R (AUROC 0.970 on the
  scored set, ECE 0.025), summarise/decline logic.
- ~/workspace/multi-agent-evidence (src + eval): multi-agent orchestration
  patterns and evaluation results discipline.
- ~/workspace/hybrid-perturb-bench: evaluation harness patterns (fixed
  splits, leakage checks, per-system report cards).

## Non-negotiable rules
R1 Temporal integrity: never train or tune on variants whose ClinVar
   classification postdates the evaluation split's cutoff.
R2 Every factual claim in a dossier carries a source. No source, no claim.
R3 Decline is a first-class output. Below the evidence bar, the dossier
   says so and names what evidence is missing.
R4 No invented numbers. All quantities come from data or tool output.
R5 Provider-agnostic LLM layer: OpenAI-compatible endpoint via env
   (base URL + key). Must support the local Hyperspace endpoint
   (http://localhost:8080/v1) for high-volume steps and hosted APIs for
   deep reasoning. The evidence/benchmark path must also run fully
   offline with no LLM key (deterministic mode) so results reproduce.

## Phases
Phase 1 (fusion): LangGraph pipeline, planner -> gatherers (ClinVar local,
  gnomAD, PubMed) -> calibrated judgment -> decline gate -> dossier
  (Markdown + JSON trace). CLI: variant in, dossier out.
Phase 2 (compute): sandboxed code execution. The agent writes analysis
  code (conservation, population stats, domain mapping), runs it in an
  isolated runner with timeouts and no network, verifies outputs, logs
  code + outputs into the dossier.
Phase 3 (critique + design): reviewer agent attacks the draft verdict;
  experiment designer proposes the functional validation that would
  settle the variant; dossier v2 includes both.
Phase 4 (proof): temporal-split benchmark of the full agent (accuracy,
  calibration, decline rate, analysis-correctness audit), public GitHub
  repo, live app under Omevra.

## Mac participation
Hyperspace CLI v5.104.6 is installed on his MacBook Air (node auto-starts).
The repo will be cloned on the Mac; the LLM base URL there points at the
Hyperspace local endpoint for cheap steps. Leo builds and tests the core
in the workspace; Umesh runs the same repo from his terminal.
