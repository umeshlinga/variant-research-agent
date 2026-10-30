# Phase 4 Benchmark Report — Variant Research Agent

Run 2026-10-30. Command:
`.venv/bin/python scripts/benchmark.py --n 300 --seed 20261030`
Wall time 77 s (0.26 s/run). Artifacts in `benchmark/`
(`sample.json`, `results.jsonl`, `summary.json`, 300 dossiers +
traces in `benchmark/dossiers/`). Every number below is computed by
the harness from those 300 actual runs — the metric functions are
unit-tested on synthetic inputs (`tests/test_benchmark.py`) and no
figure is quoted from anywhere else (R4).

## Methods

**What ran.** The FULL pipeline (planner → ClinVar/gnomAD/PubMed
gatherers → sandboxed compute → judge → decline gate → reviewer →
experiment designer → dossier writer), once per sampled variant,
in-process against one shared data layer.

**Mode: deterministic offline.** `VRA_OFFLINE=1`, live gatherers off.
No LLM endpoint was contacted; the gnomAD item in each dossier comes
from the recorded lookup in the local data, and PubMed is not queried
offline, so literature items never appear. How this differs from
live mode: (a) gnomAD values are the source project's harvested
values rather than fresh API reads; (b) neutral literature items are
absent, which lowers evidence counts slightly. Neither difference
supplies directional predictor evidence, whose absence is what drives
the declines below — but a live-mode benchmark remains a separate,
unrun experiment.

**Temporal-integrity design (R1).** The pipeline's data layer reads
only prediction-time columns; `sig_now` / `label` are whitelisted
out of every table it can touch (Phase 1, structural). The harness
reads those two columns itself, directly from the v3 test-features
table, for exactly two evaluation-side purposes: (1) stratifying the
sample, and (2) scoring finished dossiers against the temporal truth
— what ClinVar says *now* about variants that were uncertain at the
2024-01 freeze. Truth is never passed to the pipeline; each run
receives only the string `allele:<id>`. Scoring happens after the
dossier files are written.

**Sampling frame — stated honestly, including its hole.** The frame
is the vus-evidence-agent temporal test set: 27,748 rows, 27,742
unique allele ids (the source table contains 6 exact duplicate rows,
all in the pseudoautosomal genes SHOX and CSF2RA; the pipeline
resolves by allele id, so duplicates are indistinguishable and the
frame is counted in unique variants). Strata: recorded GBM+R
probability available (allele present in
`test_predictions_trees.csv`; 10,357 of 27,742) × eventual truth.

| Stratum | Frame | Sampled |
|---|---:|---:|
| prob available × pathogenic-leaning truth | 4,702 | 50 |
| prob available × benign-leaning truth | 5,655 | 61 |
| prob unavailable × pathogenic-leaning truth | 4,154 | 46 |
| prob unavailable × benign-leaning truth | 13,237 | 143 |
| **still-uncertain truth (either prob stratum)** | **0** | **0** |

Proportional allocation (largest remainder), fixed seed 20261030.

The third truth category requested for this benchmark —
**still-uncertain — has zero members, and that is a property of the
data, not a sampling choice.** The temporal test set is *defined*
(SPLIT_REPORT.md in the source project) as variants that were
uncertain at the freeze **and have since been reclassified**; a
variant still uncertain today is by construction not in it. No
sample could be drawn from that stratum, and §"What this does not
prove" below takes the consequence seriously.

## Results

### Coverage and verdicts

| | n |
|---|---:|
| Sampled | 300 |
| Resolved and run end-to-end | 300 (coverage 1.000 — see caveat) |
| Concluded pathogenic-leaning | 50 |
| Concluded benign-leaning | 61 |
| DECLINED | 189 |

Coverage caveat: the sample was drawn from the resolvable table, so
1.000 coverage is by construction. It confirms the pipeline runs the
full table's range without crashing; it is not evidence about
variants outside the local tables, which the resolver rejects by
design.

### The basis split — the benchmark's central structural finding

Conclusion behaviour splits *exactly* on recorded-probability
availability:

| | Concluded | Declined |
|---|---:|---:|
| GBM+R basis (prob available), n = 111 | **111** | 0 |
| Evidence-scoring basis (no prob), n = 189 | 0 | **189** |

And every decline came through the judgment path, never the count
path: all 189 declined cases had 3–6 evidence items (the ≥ 3 bar was
met) but an *indeterminate* fallback judgment — evidence score 0 in
178 cases, ±1 in the other 11, never reaching the |score| ≥ 2 a lean
requires. The mechanism is visible in the evidence composition: the
declined cases carry an AlphaMissense item in **0/189** cases and a
REVEL item in only **14/189**, while concluded cases carry REVEL in
111/111. The remaining items (frozen ClinVar status — neutral for
variants that were VUS/conflicting at the freeze; gene prior —
neutral; gnomAD — directional only at AF ≥ 0.01; agent analyses —
neutral by design) cannot sum to a lean. The recorded GBM+R set is,
in this data, essentially the subset of variants that had complete
predictor features; outside it there is usually no directional
predictor evidence to score. The agent's conclude/decline boundary
is therefore the model's coverage boundary — the system concludes
exactly where calibrated support exists and declines exactly where
it does not.

### Accuracy and calibration (concluded cases)

| Metric | Value | Reference |
|---|---:|---:|
| Accuracy on concluded (n = 111) | **0.8919** (99/111) | — |
| … pathogenic-truth cases (n = 50) | 0.880 (44/50) | — |
| … benign-truth cases (n = 61) | 0.902 (55/61) | — |
| ECE, concluded scored subset (n = 111) | **0.0513** | 0.0248 (full set, n = 10,357) |
| Brier, concluded scored subset | **0.0833** | 0.0625 (full set) |
| AUROC on the sample (supplementary) | 0.9518 | 0.9705 (full set) |

The concluded and all-scored calibration sets are identical here
because every scored case concluded. Sample figures are noisier
than the full-set MODEL_REPORT_6 figures (n = 111, and isotonic
calibration produces only 17 distinct probability values across the
111 — plateaus, not per-variant precision); the gaps are consistent
with sampling noise and are not, on this n, evidence that the
recorded probabilities misbehave inside the agent.

### Declines

| Metric | Value |
|---|---:|
| Decline rate | 0.630 (189/300) |
| Decline precision | **1.000** (189/189 protective, 0 over-cautious) |

Decline precision = the fraction of declined cases where forcing a
conclusion from the agent's own underlying judgment would not have
produced a correct verdict (judgment indeterminate, or leaning
against the truth). It is a perfect score, and its meaning is
bounded by the basis split above: the fallback judge never formed a
lean at all on these cases (178 of 189 scored exactly 0), so there
was no right answer sitting underneath a decline. What it does
establish: in 300 runs the gate never suppressed a conclusion the
system's own scoring had already reached correctly.

### Reviewer behaviour

| Metric | Value |
|---|---:|
| Concluded cases with ≥ 1 material critique | 111/111 |
| Downgraded | 104/111 (0.937) — 79 strong→moderate, 25 moderate→weak |
| Not downgraded | 7 — all already "weak", all with material critiques |
| Downgrade rate among *correct* conclusions | 96/99 = 0.970 |
| Downgrade rate among *wrong* conclusions | 8/12 = 0.667 |
| Accuracy of downgraded conclusions | 96/104 = 0.923 |
| Accuracy of non-downgraded conclusions | 3/7 = 0.429 |

Read carefully: **downgrades do not concentrate on errors — they
concentrate on correct conclusions.** The driver is
`strength_thin_independent_support`, which fired in **111/111**
concluded cases: a GBM+R verdict's directional support almost
always traces to a single independent family (the correlated
missense predictors; gnomAD supports directionally only for common
benign-leaning variants), so the one-step strength challenge is
close to a constant of this pipeline configuration, not a
discriminator. The 7 non-downgraded cases are not "reviewer-approved"
cases: all seven sat on the same isotonic plateau (P = 0.4642, just
under 0.5 → "weak" benign leans), already at the weakest band with
material critiques the reviewer could not act on — and 4 of the 7
were wrong. The reviewer's measured value in this benchmark is the
audit trail (every weakness named in every dossier), not error
detection.

### Analysis execution (Phase 2 audit)

900 agent analyses executed across the 300 runs (3 per run):
**0 failed, 0 timed out.** Every run's compute stage completed; where
an analysis had no computable content it reported `no_content` and
correctly contributed no evidence (the RYR1 pattern from Phase 2,
at scale).

## Failure examples — concluded, confident, wrong

The harness ranks concluded-but-wrong cases by confidence of error;
these are the top three. There were 12 wrong conclusions in total
(6 pathogenic leans on benign truth, 6 benign leans on pathogenic
truth).

### 1. IL7R NM_002185.5:c.602A>G (p.Tyr201Cys), allele 303867

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.979,
downgraded strong → moderate. Evidence: AlphaMissense 0.964
(likely pathogenic), REVEL 0.864 — both predictors pathogenic;
frozen ClinVar record itself "Conflicting interpretations".
**Truth:** ClinVar now says **Likely benign**.
**Reviewer caught:** predictor *disagreement* existed — the agent's
own agreement analysis reported only 1/3 pairwise agreement (the
gene prior leaned benign) — but at **notable** severity, because the
majority consensus was pathogenic; and the conflicting frozen
ClinVar record (notable). **Missed:** no material direction conflict
fired, because the two *gathered* directional items agreed; the
disagreement lived in the derived analysis, one severity band too
low to name this a contested case.

### 2. CHD2 NM_001271.4:c.1718C>T (p.Thr573Met), allele 949112

**Dossier said:** benign-leaning, P(pathogenic) = 0.022, downgraded
strong → moderate. Evidence: AlphaMissense 0.064 (likely benign);
REVEL 0.295 (neutral band); everything else neutral.
**Truth:** ClinVar now says **Likely pathogenic**.
**Reviewer caught:** predictor disagreement (notable, 1/3 pairwise)
and, pointedly, `conflict_model_vs_evidence_sum` — "outside the
model, the raw evidence directions sum to indeterminate (−1); the
strong language rests on the model probability alone" (notable).
**Missed:** nothing reached material except the structural strength
challenge. A P = 0.022 resting on effectively one directional
predictor is the thin-support pattern the reviewer exists to flag,
and it did — as language. The lean follows the recorded model by
design, so the conclusion stood and was wrong.

### 3. MECP2 NM_001110792.2:c.1483G>A (p.Glu495Lys), allele 264950

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.949,
downgraded strong → moderate. Evidence: AlphaMissense 0.981
(likely pathogenic); REVEL 0.500 (neutral band).
**Truth:** ClinVar now says **Benign**.
**Reviewer caught the substantive problem, at full severity:**
`conflict_predictor_split` — **material** — the agent's agreement
analysis reported a split consensus (1 pathogenic / 1 benign /
1 indeterminate lean, 0/3 pairwise agreement), plus the
model-vs-evidence-sum notable (raw sum +1, indeterminate). It
downgraded accordingly. **The limit this exposes:** the reviewer's
only power is confidence language. It identified a genuinely
contested evidence picture, said so in the dossier, weakened the
wording — and the verdict still followed the model into the wrong
conclusion. If the reviewer is ever to change outcomes, a material
split-consensus would be the place to give it a second power
(e.g. forcing a decline); this benchmark deliberately did not,
because BUILD_PLAN R3 reserves the gate to evidence count and
judgment decisiveness.

## What this does and does not prove

**It does prove**

- The assembled system behaves coherently at scale: 300/300 runs
  completed, 900/900 sandboxed analyses executed without a failure
  or timeout, every dossier written with its full audit trail.
- The system's conclusion boundary coincides with calibrated
  support: it concluded all and only the cases carrying a recorded
  calibrated probability, at 0.8919 accuracy against the temporal
  truth, with sample calibration (ECE 0.0513) in the neighbourhood
  of the model's full-set calibration.
- The decline rule is safe in the specific sense measured: it never
  suppressed a correct conclusion the underlying scoring had
  reached (decline precision 1.000, 0 over-cautious declines).
- The reviewer produces a complete, specific critique of every
  concluded dossier — no silent passes.

**It does not prove**

- **Anything about variants that are still VUS today.** That truth
  stratum is empty in the test set by construction. The 63% decline
  rate is *not* an estimate of how often the agent would decline in
  a clinic today; the population here is "variants history has
  already judged."
- **Anything about variants outside the local tables.** Resolution
  is table-bound and coverage 1.000 is an artifact of sampling from
  the resolvable table.
- **That the agent adds discrimination over the recorded model.** On
  concluded cases the verdict *is* the recorded model's output,
  passed by a gate whose count bar never fired in this sample and a
  reviewer that cannot change leans. The agent's measured added
  value is the decline behaviour, the computed context, the
  critique, and the audit trail — not accuracy beyond the model's.
- **That the reviewer detects errors.** It does not, as built: its
  material strength challenge fires on ~every model verdict
  (111/111), downgrades were *more* frequent among correct
  conclusions (97.0%) than wrong ones (66.7%), and its one
  substantive catch among the top failures (MECP2) could only weaken
  wording. The Phase 3 open question — whether the independence
  families are drawn right — is answered in part here: as a
  *discriminator* the current taxonomy fails; as an *audit* it is
  complete.
- **Live-mode behaviour.** gnomAD/PubMed live calls were off for
  reproducibility; LLM stages were off (no endpoint). The live and
  LLM paths are implemented and unit-tested with mocked/fake
  clients, but no number in this report describes them.
- **Clinical validity.** The truth standard is ClinVar's current
  classification, which the source split report itself notes is
  partly predictor-influenced; these are research metrics on a
  research dataset, not evidence for clinical use.

## Release preparation — state and checklist

Prepared in this phase (nothing published):

- [x] `scripts/benchmark.py` — the harness above; metric functions
      unit-tested; full suite green (**48 tests**).
- [x] BENCHMARK_REPORT.md — this file.
- [x] README.md — polished: benchmark headline table, full pipeline,
      honesty rules, offline + live + LLM (incl. Hyperspace
      `http://localhost:8080/v1`) run instructions, example links.
- [x] LICENSE — MIT, © 2026 Umesh Linga.
- [x] RELEASE_NOTES.md — draft notes for v0.4.0.
- [x] `space/` — Hugging Face Space skeleton (Gradio `app.py`
      wrapping the pipeline for one variant, offline default;
      `requirements.txt`; Space `README.md`). Smoke-tested locally
      with a stubbed Gradio: it reproduces the pipeline's ARSB and
      RYR1 verdicts. **Not deployed.**

Not done — deliberately, pending the owner's decisions:

- [ ] Push to GitHub / create the remote repo (release action,
      owner's call; nothing was pushed or committed in this phase).
- [ ] Deploy the Space (blocked on a data decision: a deployment
      needs the processed tables via `VRA_VUS_HOME`, whose
      redistribution terms belong to the source project; and on the
      secrets policy for any future LLM key).
- [ ] Verify LLM mode against a live endpoint (the Mac + Hyperspace
      node check carried over from Phases 1–3).
- [ ] Fresh GBM+R inference (`model.predict_fresh` remains an
      adapter stub — there is no serialised model artifact), which
      is the change that would let the agent conclude on variants
      outside the recorded 10,357 — and would require re-running
      this benchmark before any claim changed.
