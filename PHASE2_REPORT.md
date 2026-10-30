# Phase 2 Report — Compute stage: the agent runs its own analyses

Phase 2 adds a COMPUTE stage between the gatherers and the judge. The
agent now produces analysis code, executes it in a sandbox, and cites
the computed results as evidence in the dossier. Pipeline:

```
planner -> gather_clinvar -> gather_gnomad -> gather_pubmed
        -> compute -> judge -> decline_gate -> dossier_writer
```

All work is inside this project. The three source projects
(vus-evidence-agent, multi-agent-evidence, hybrid-perturb-bench) are
untouched; their data is read in place, prediction-time columns only
(R1 preserved).

## What was built

### New modules

- `src/variant_research_agent/sandbox.py` — the sandbox runner.
  `run_script(name, source, inputs, timeout=30.0, origin)` executes a
  script and returns an `AnalysisResult` (status, summary, computed
  results, script SHA-256, full script source, stdout, stderr, exit
  code, duration, error).
- `src/variant_research_agent/compute.py` — the compute stage: three
  analysis templates, trusted-side input preparation, the optional
  LLM script-proposal path, and `run_analyses()` which the graph
  calls.

### Schema and data additions

- `schema.py`: `AnalysisResult` model. `counts_as_evidence` is True
  only when the script ran cleanly AND reported real computed
  content; that single flag is what the evidence conversion checks.
- `data.py`: `LocalData.test_rows()`, `column_distribution(column)`
  (non-null values of a prediction-time column across the local test
  set), and `gene_prior_distribution()`. These supply the reference
  distributions the analyses compute against: 18,225 recorded gnomAD
  AFs, 10,373 AlphaMissense scores, 11,023 REVEL scores from the
  v3 test set (27,748 variants).

### The three analyses

Each analysis is a small, self-contained, stdlib-only Python script
generated from a parameterized template. Inputs are prepared on the
trusted side from the resolved record, the gathered evidence, and
the local tables — every number in an output is computed from those
inputs (R4). Contract: read `inputs.json`, write `result.json` with
`{summary, results, has_content}`, print the summary. When a needed
datum is missing, the script says so in its summary and reports
`has_content: false` rather than inventing a number.

1. **population_context** — the variant's gnomAD allele frequency
   placed inside the local test set's AF distribution: midrank
   percentile, reference size and median, fraction of reference
   variants at least as common, and a rarity class
   (common / low-frequency / rare). AF source preference: a live
   lookup's value, then the record's stored frequency at full
   precision, then a recorded item's parsed value.
2. **predictor_agreement** — agreement statistics across
   AlphaMissense, REVEL, and the gene prior: per-predictor leans
   (REVEL thresholds 0.644 / 0.290 per Pejaver et al. 2022, matching
   the gatherers), lean counts, pairwise agreement fraction, and a
   consensus label (unanimous / majority / split / neutral). Needs
   at least 2 predictors or it reports no content.
3. **score_percentiles** — local distribution context: the variant's
   AlphaMissense and REVEL scores as percentiles of the local
   test-set distributions of those scores.

### LLM script proposals (optional, R5)

When an LLM endpoint is configured AND reachable, the stage may ask
it to propose a script body for an analysis. A proposal is used only
if it compiles, imports nothing beyond `json` / `math` /
`statistics`, contains no banned tokens (socket, urllib, requests,
subprocess, eval, exec, `__import__`, os.system, popen, shutil,
pathlib), and references both `inputs.json` and `result.json`. It
then runs in the same sandbox under the same contract. Any failure
at any point falls back to the template, and the fallback is logged
in the run events. The offline deterministic path never touches this
code and always works.

### Pipeline integration

- `graph.py`: new `compute` node between `gather_pubmed` and
  `judge`; the planner's step list (template and LLM prompt) names
  the stage. Judge and gate code are unchanged.
- Analysis results become evidence items with source
  `Agent analysis: <name>` and source id
  `ANALYSIS:<name>:<script-sha256[:12]>` — but only when
  `counts_as_evidence` is set. Failed, timed-out, and empty analyses
  are recorded in the dossier and trace and never count toward the
  3-item decline bar.
- Analysis items are direction-NEUTRAL by design: their directional
  signal derives from the same predictors the gatherers already
  cite, so giving them a direction would double-count those
  predictors in the judge's fallback sum. They contribute
  independent computed context and gate weight, not a second vote.
- `dossier.py`: new "Analyses run by the agent" section — each
  analysis with its origin (template/LLM), short script hash,
  duration, status, computed summary, and an explicit line for
  whether it counted as evidence; failures show their error. The
  JSON trace now includes the full `analyses` array: script sources,
  inputs-derived results, stdout/stderr, exit codes.
- `__main__.py`: CLI prints an analyses line (count run, count
  counted, per-analysis statuses).

## Sandbox design — and its limits, stated precisely

Design:

- Each run gets a fresh temporary directory (`vra_sandbox_*`),
  deleted afterwards. The script, `inputs.json`, and a runner
  wrapper are the only files placed there; `HOME` and `TMPDIR`
  point inside it.
- Separate process (`sys.executable` on the wrapper), with a
  scrubbed environment: no proxy variables, no inherited API keys or
  credentials, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`.
- No network: the wrapper replaces `socket.socket` with a class that
  raises on construction and blocks `create_connection`,
  `create_server`, and the DNS lookup functions before the analysis
  code runs.
- Hard timeout (default 30 s): the subprocess is killed on expiry
  and the analysis is recorded as `timeout`. POSIX resource limits
  in the child: CPU time (timeout + 5 s), 16 MB max file size, no
  core dumps.
- Contract enforcement: exit 0 without a valid `result.json` is a
  recorded failure ("contract violation"), not a silent pass.
  stdout/stderr are captured and truncated to the last 8,000
  characters in the trace.

Limits (what this is NOT):

- This is process isolation plus timeouts around the agent's own
  generated scripts. It is **not a security proof against hostile
  code**. The child runs as the same OS user; the socket wrapper
  stops ordinary network use, but a determined hostile script could
  attempt filesystem access outside the sandbox directory or other
  escapes that only an OS-level sandbox (containers, seccomp,
  separate user, VM) would reliably prevent. The templates are
  ours and deterministic; the LLM-proposal screen is a filter, not
  a proof. Do not point this runner at untrusted third-party code
  and call it safe.
- Memory is bounded only indirectly (CPU/time/file limits); there
  is no hard RSS cap in this implementation.
- The timeout kills the runner process; because analyses run
  in-process inside the runner, no orphaned grandchildren are
  expected from template or screened scripts.

## Tests

Full suite: **30 passed** (17 Phase 1 + 13 new), offline, no network.

New coverage:

- `tests/test_sandbox.py` (6): happy-path contract; network blocked
  two ways (raw `socket.socket()` construction and
  `socket.create_connection` — both fail, the success marker never
  prints, and the create_connection case surfaces the wrapper's
  "network access is disabled" error); sleep-past-timeout script
  killed and recorded as `timeout`; raising script recorded as
  `failed` with the exception named; exit-0-without-result.json
  recorded as a contract failure.
- `tests/test_compute.py` (7): evidence conversion only for real
  content (failed/timeout/no_content convert to nothing); input
  preparation reads real data (ARSB AF, gene prior, reference sizes);
  all three analyses run `ok` on ARSB with the expected computed
  values (unanimous pathogenic consensus, agreement fraction 1.0);
  the thin RYR1 variant yields three `no_content` analyses and zero
  items; a monkeypatched raising template yields a `failed` analysis
  and the evidence count drops from 3 to exactly 2 (failures do not
  inflate); end-to-end ARSB run shows the new dossier section, the
  trace carries script sources and results, evidence count is
  5 gathered + 3 computed = 8; end-to-end RYR1 run still DECLINES
  at exactly 1 evidence item.
- The Phase 1 gate tests now stub the compute stage alongside the
  gatherers, so they keep isolating gate behaviour exactly as
  before (gate logic itself unchanged).

## Example results (regenerated, offline, compute on)

Files in `examples/` (full dossiers + JSON traces in `runs/`).

### ARSB NM_000046.5:c.1178A>C (p.His393Pro) — pathogenic-leaning

Verdict unchanged (GBM+R P = 0.989); evidence 5 -> 8 items.

- population_context: gnomAD AF 7.66e-05 sits at the 83.3th
  percentile of the 18,225 recorded AFs in the local test set
  (median 1.23e-05); rarity class rare. Reading: absolutely rare,
  but less rare than most variants in this reclassification-enriched
  test set — exactly the kind of context a raw AF hides.
- predictor_agreement: 3 pathogenic leans, 0 benign, 0
  indeterminate; pairwise agreement 3/3; consensus pathogenic
  (unanimous).
- score_percentiles: AlphaMissense 0.709 at the 62.8th percentile
  and REVEL 0.906 at the 82.8th percentile of the local test-set
  distributions — high, but not extreme within this enriched set.

### NHERF1 NM_004252.5:c.328C>G (p.Leu110Val) — benign-leaning

Verdict unchanged (GBM+R P = 0.012); evidence 5 -> 8 items.

- population_context: AF 0.0263 at the 99.8th percentile of the
  local AF distribution; rarity class common (AF >= 0.01).
- predictor_agreement: 3 benign leans; pairwise agreement 3/3;
  consensus benign (unanimous).
- score_percentiles: AlphaMissense 0.095 at the 20.4th percentile,
  REVEL 0.070 at the 11.0th percentile of the local distributions.

### RYR1 NM_000540.3:c.14761_14762delinsAC — still DECLINED

All three analyses ran and honestly reported no computable content:
no gnomAD frequency exists for this variant, fewer than 2
predictors have scores (none do — a delins), and there are no
AlphaMissense/REVEL scores to place. Evidence count stays at 1 (the
frozen ClinVar item); the dossier still DECLINES and names the
missing evidence. This is the Phase 2 honesty check end to end:
the compute stage cannot manufacture its way past the bar.

## Limitations

- Reference distributions come from the local temporal test set,
  which is enriched for reclassified (hence often higher-scoring,
  higher-AF) variants. Percentiles are context within that set —
  the dossiers say so — not population percentiles.
- The judge still consumes recorded GBM+R probabilities
  (10,357 of 27,748 test variants); the compute stage does not
  extend model coverage, and `predict_fresh()` remains a stub (no
  serialized model artifact exists in the source project).
- Analysis inputs are limited to what Phase 1 gathers: the gene
  prior enters agreement statistics via the recorded predictions
  table, so variants outside that table lose one predictor there.
- The LLM-proposal path is exercised only when an endpoint is
  reachable; in this environment it was verified by construction
  (screen + sandbox + fallback) and by the offline test suite, not
  by a live LLM run.
- Live-mode nuance: with `--live`, a fresh gnomAD frequency wins
  over the recorded one in population_context, but the reference
  distribution remains the local test set's recorded AFs — the
  comparison set is frozen even when the variant's value is fresh.
