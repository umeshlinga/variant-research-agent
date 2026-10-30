# Release notes — DRAFT (not yet released)

## Variant Research Agent v0.4.0 — "the one that shows its work"

An autonomous research agent for human genetic variants. Variant in,
auditable research dossier out — or an honest decline when the
evidence is too thin. Built by fusing three earlier projects
(vus-evidence-agent, multi-agent-evidence, hybrid-perturb-bench).

### What it does

- **Plans** an investigation for a variant (LLM when an endpoint
  answers, deterministic template otherwise).
- **Gathers** evidence: frozen ClinVar status, AlphaMissense, REVEL,
  gene prior, gnomAD frequency, PubMed literature (live only) — every
  item cited by source identifier.
- **Computes**: the agent generates small Python analyses (population
  context, predictor agreement, score percentiles) and runs them in a
  no-network sandbox; only analyses with real computed content become
  evidence. Failures are shown, never hidden.
- **Judges** with the calibrated GBM+R model recorded by
  vus-evidence-agent (MODEL_REPORT_6: AUROC 0.9705 on the temporal
  test set), with a transparent evidence-score fallback for variants
  the model never scored.
- **Declines** below the cite-or-decline bar (< 3 evidence items, or
  an indeterminate judgment), naming what is missing.
- **Reviews itself**: a deterministic adversarial reviewer checks
  independence, direction conflicts, missing classes, calibration
  caveats, and strength vs support, and may downgrade confidence
  language one step — never upgrade, never reverse a decline.
- **Designs** the validation experiments that would settle the
  variant, declined cases included, with pre-stated outcomes.

### Phase 4 benchmark (the proof, not the promise)

On a stratified 300-variant sample of the temporal test set
(deterministic offline mode, 77 s):

- Accuracy on concluded cases: **0.8919** (99/111). All 111 concluded
  cases carry a recorded GBM+R probability; every no-probability
  case declined.
- Calibration on the concluded scored subset: **ECE 0.0513,
  Brier 0.0833** (model's own full-set figures: ECE 0.0248,
  Brier 0.0625, n = 10,357).
- Decline rate **0.630**; decline precision **1.000** — no declined
  case had an underlying judgment that already leaned the right way.
- Reviewer: material critique in **111/111** concluded cases,
  downgrades in **104/111**. Honest caveat in the full report: the
  strength challenge fires on nearly every model verdict, so
  downgrades do **not** concentrate on errors (97.0% of correct
  conclusions were downgraded, 66.7% of wrong ones) — the reviewer
  weakens language, it does not rescue wrong leans.

See BENCHMARK_REPORT.md for methods, the sampling frame, the empty
still-uncertain stratum, failure examples, and what this does and
does not prove.

### Honest limitations (in the release, not hidden from it)

- The pipeline only resolves variants present in the local
  vus-evidence-agent processed tables; no live ClinVar retrieval.
- Recorded GBM+R probabilities cover 10,357 of the 27,748 temporal
  test variants; the rest are judged by uncalibrated evidence scoring
  and, in this benchmark, always declined.
- The benchmark's still-uncertain truth stratum is empty by
  construction (the test set contains only variants that were
  reclassified), so nothing here is proven about variants that
  remain VUS today.
- The sandbox is process isolation plus timeouts — not a security
  proof against hostile code.
- **Not for clinical use. Research / portfolio project only.**

### Status

Prepared for release: README, LICENSE (MIT), BENCHMARK_REPORT.md, and
a Hugging Face Space skeleton (`space/`) are in place. Nothing has
been pushed to GitHub and nothing has been deployed.
