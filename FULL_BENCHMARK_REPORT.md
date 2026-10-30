# Full-Set Benchmark Report — Variant Research Agent

Run 2026-10-30. Command (three sessions, see "Execution history"
below): `.venv/bin/python scripts/benchmark_full.py --workers 2
--out benchmark/fullset`
Total wall time 104.0 min across the three sessions for
27742 variants (parallel pool,
2 workers on the 2-core bench VM; measured rate at the first 500
completions: see run log, projected total ~96 min at that rate).
Artifacts in `benchmark/fullset/` (`results.jsonl` — the incremental
checkpoint, `summary.json`, 55484
dossier/trace files in `dossiers/`). Every number below is computed
from those 27742 actual runs by `scripts/analyze_full.py`;
no figure is quoted from anywhere else (R4). This report supersedes
the 300-variant sample estimates in `BENCHMARK_REPORT.md` with
population values; the sample report remains the record of that run.

## Methods

**What ran.** The FULL pipeline (planner → ClinVar/gnomAD/PubMed
gatherers → sandboxed compute → judge → decline gate → reviewer →
experiment designer → dossier writer), once per variant, over the
ENTIRE temporal test set: all 27742 unique allele ids (the
source table's 27,748 rows contain 6 exact duplicate rows in SHOX
and CSF2RA; the pipeline resolves by allele id, so the universe is
counted in unique variants, exactly as in the sample report).

**Mode: deterministic offline.** `VRA_OFFLINE=1`, live gatherers off
— identical to the sample benchmark. gnomAD items come from the
recorded lookup; PubMed is not queried offline.

**Temporal integrity (R1).** Identical design to the sample harness:
the pipeline's data layer structurally cannot read `sig_now` /
`label`; this runner reads them evaluation-side only (via
`scripts/benchmark.py: load_truth`), for post-hoc scoring. Truth is
never passed to the pipeline; each run receives only the string
`allele:<id>`.

**Checkpointing.** Results were appended to `results.jsonl` as each
run completed (flush per record, fsync every 1,000), and the runner
skips allele ids already present on startup — an interruption loses
at most the in-flight chunk and the run resumes without redoing
completed variants. Resume behaviour was verified on a 30-variant
smoke run before the full launch.

**Execution history (stated plainly, per R4).** The full set took
three sessions. Session 1 completed 4,093 resolved runs, then its
detached process lost subprocess permission in this sandbox
environment: every subsequent run failed fast with
`PermissionError: [Errno 1] Operation not permitted` (15,923 error
records), and the process died at 20,020 records (~22.8 min). The
pipeline itself was not at fault — the same variants run cleanly in
a fresh session, verified directly. Session 2 (resume, 26.6 min)
completed the remaining 7,722 untouched variants, but the runner's
checkpoint then still counted session 1's error records as done, so
its first summary covered only 11,819 resolved variants and is
superseded by this report. Two runner fixes followed: error records
are never checkpointed as done (a resume retries them), and
`PermissionError` results are not written at all, with an early
abort if the environment is still blocked. Session 3 re-ran exactly
the 15,923 error variants (54.6 min) and completed the
set. Final tally: 27742 unique variants, every one resolved
through the real pipeline; no variant's result comes from a failed
run.

**Decline precision — definition (unchanged from the sample report,
so the numbers are comparable).** Of the DECLINED cases, the fraction
where forcing a conclusion from the agent's own underlying
(pre-gate) judgment would not have produced a correct verdict:
judgment indeterminate, or leaning against the truth, or truth still
uncertain. The complement is the over-cautious count: declined
although the underlying lean already matched the truth.

## Sample vs full set — how the estimates held up

| Metric | 300-sample | Full set |
|---|---:|---:|
| Variants run | 300 (stratified sample) | 27742 (full set) |
| Concluded | 111 | 10359 |
| Declined | 189 | 17383 |
| Decline rate | 0.6300 | 0.6266 |
| Accuracy on concluded | 0.8919 (n=111) | 0.9214 (n=10359) |
| AUROC on concluded | 0.9518 (n=111) | 0.9705 (n=10357) |
| ECE, concluded scored | 0.0513 | 0.0248 |
| Brier, concluded scored | 0.0833 | 0.0625 |
| Decline precision | 1.0000 | 1.0000 |
| Over-cautious declines | 0 | 0 |
| Reviewer material-critique rate (concluded) | 1.000 (111/111) | 0.9964 (10322/10359) |
| Downgrade rate (concluded) | 0.9369 | 0.9235 |
| Sandbox analyses failed / timed out | 0 / 0 | 0 / 0 |

## Results

### Coverage and verdicts

| | n |
|---|---:|
| Unique variants in universe | 27742 |
| Resolved and run end-to-end | 27742 (coverage 1.0000) |
| Unresolved / errored | 0 |
| Concluded pathogenic-leaning | 4530 |
| Concluded benign-leaning | 5829 |
| DECLINED | 17383 |

Coverage caveat (unchanged from the sample report): the universe is
drawn from the resolvable local table, so coverage near 1.000
confirms the pipeline runs the full table's range without crashing;
it is not evidence about variants outside the local tables, which
the resolver rejects by design.

### The basis split

| | Concluded | Declined |
|---|---:|---:|
| GBM+R basis (recorded prob available), n = 10357 | 10357 | 0 |
| Evidence-scoring basis (no prob), n = 17385 | 2 | 17383 |

Decline mechanism: 17383 of 17383 declines carried an
indeterminate fallback judgment; evidence score was exactly 0 in
16737 declined cases. Evidence composition: declined cases
carry an AlphaMissense item in 16/
17383 cases and a REVEL item in 664/
17383; concluded cases carry REVEL in
10359/10359. (Sample report,
for comparison: declines with AM 0/189, REVEL 14/189; concluded with
REVEL 111/111.)

### Accuracy and calibration (concluded cases)

| Metric | Value |
|---|---:|
| Accuracy on concluded (n = 10359) | **0.9214** (9545 correct) |
| … pathogenic-truth cases (n = 4702) | 0.8952 (4209 correct) |
| … benign-truth cases (n = 5657) | 0.9433 (5336 correct) |
| AUROC, concluded scored (n = 10357) | **0.9705** |
| ECE, concluded scored subset (n = 10357) | **0.0248** |
| Brier, concluded scored subset | **0.0625** |
| ECE / Brier, all scored resolved (n = 10357) | 0.0248 / 0.0625 |

Model reference (MODEL_REPORT_6, recorded GBM+R on its full scored
set, n = 10,357): AUROC 0.9705, ECE 0.0248, Brier 0.0625. 10,357 of
the 10,359 concluded cases are exactly the recorded-probability set
(the other 2 concluded through the evidence-scoring path — see the
basis split), so the agent's concluded AUROC/calibration are the
model's own population values as passed through the gate — the gate
and reviewer do not alter leans or probabilities.

### Declines

| Metric | Value |
|---|---:|
| Decline rate | 0.6266 (17383/27742) |
| Decline precision | **1.0000** (17383 protective, 0 over-cautious) |

### Reviewer behaviour

| Metric | Value |
|---|---:|
| Concluded cases with ≥ 1 material critique | 10322/10359 (0.9964) |
| Downgraded | 9567/10359 (0.9235) |
| Downgrade rate among *correct* conclusions | 9037/9545 = 0.9468 |
| Downgrade rate among *wrong* conclusions | 530/814 = 0.6511 |
| Accuracy of downgraded conclusions | 0.9446 (n = 9567) |
| Accuracy of non-downgraded conclusions | 0.6414 (n = 792) |

### Analysis execution (Phase 2 audit)

83226 agent analyses executed across the
27742 resolved runs. Status totals: no_content = 43605, ok = 39621.
Runs with all analyses clean (no failure, no timeout):
27742/
27742 (1.0000).

## Failure gallery — concluded, most confident, wrong

Ranked by confidence of error (the harness's
`pick_failure_examples`, top 10 of 814 wrong conclusions
in total).

### 1. GCK NM_000162.5(GCK):c.203G>A (p.Gly68Asp), allele 961077

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.999, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 2. SCN1A NM_001165963.4(SCN1A):c.2722G>A (p.Gly908Ser), allele 1687881

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.999, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 3. CARS2 NM_024537.4(CARS2):c.655G>A (p.Ala219Thr), allele 178316

**Dossier said:** benign-leaning, P(pathogenic) = 0.003, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Pathogenic/Likely pathogenic**. **Reviewer note:** Strength challenge: the 'strong' benign language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong'.

### 4. RYR1 NM_000540.3(RYR1):c.11798A>G (p.Tyr3933Cys), allele 136769

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.996, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 5. GLUD1 NM_005271.5(GLUD1):c.452G>C (p.Arg151Pro), allele 1009266

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.996, strength moderate (downgraded from strong), 7 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 6. GRIN2B NM_000834.5(GRIN2B):c.427T>C (p.Phe143Leu), allele 1047823

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.996, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 7. DLX3 NM_005220.3(DLX3):c.506C>T (p.Thr169Met), allele 2078409

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.996, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 8. SLC26A4 NM_000441.2(SLC26A4):c.1061T>C (p.Phe354Ser), allele 52662

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.995, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

### 9. PSEN1 NM_000021.4(PSEN1):c.566A>G (p.Tyr189Cys), allele 1011193

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.995, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Likely benign**. **Reviewer note:** Direction conflict among the gathered evidence: REVEL (Zenodo 7072866) (REVEL score=0.960) lean(s) pathogenic, while AlphaMissense (AlphaMissense score=0.286 class=likely_benign) lean(s) benign. No independent evidence t...

### 10. HNF1A NM_000545.8(HNF1A):c.1136C>A (p.Pro379His), allele 1388781

**Dossier said:** pathogenic-leaning, P(pathogenic) = 0.995, strength moderate (downgraded from strong), 8 evidence items. **Truth:** ClinVar now says **Benign**. **Reviewer note:** Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong...

## What this does and does not prove

The population run confirms or corrects the sample report's claims
at full scale; the "does not prove" list from the sample report is
unchanged and still binding:

- **Nothing about variants still VUS today** — that truth stratum is
  empty in the test set by construction. The decline rate is not an
  estimate of clinical decline frequency.
- **Nothing about variants outside the local tables.**
- **No added discrimination over the recorded model** — on concluded
  cases the verdict is the recorded model's output; the agent's
  measured added value is the decline behaviour, the computed
  context, the critique, and the audit trail.
