# Variant Research Agent

An autonomous research agent for human genetic variants: it plans an
investigation, gathers evidence (ClinVar, gnomAD, literature), runs
its own analyses in a sandbox, judges with a calibrated model,
critiques its own verdict, designs the validation experiment, and
publishes an auditable research dossier — or **declines** when the
evidence is too thin.

Capstone build fusing three earlier projects: vus-evidence-agent
(temporal-split data, calibrated GBM+R model, cite-or-decline rule),
multi-agent-evidence (orchestration and reliability discipline), and
hybrid-perturb-bench (evaluation discipline).

> Not for clinical use. Research / portfolio project only.
> Licence: MIT (see LICENSE).

## Benchmark headline (full set, offline, n = 27,742)

The entire vus-evidence-agent temporal test set, full pipeline,
deterministic offline mode, every variant run end to end. Every
number below comes from the recorded run in `benchmark/fullset/` —
see **FULL_BENCHMARK_REPORT.md** for methods, the failure gallery,
and what this does and does not prove. (The earlier 300-variant
sample estimates in BENCHMARK_REPORT.md are superseded by these
population values; that report remains the record of the sample run.)

| Metric | Value |
|---|---|
| Coverage (variants resolved and run end-to-end) | 27,742/27,742 |
| Concluded / declined | 10,359 / 17,383 (decline rate 0.6266) |
| Accuracy on concluded cases | **0.9214** (9,545/10,359) |
| AUROC, concluded scored cases | **0.9705** (n = 10,357) |
| Calibration, concluded scored subset | ECE 0.0248, Brier 0.0625 (n = 10,357) |
| Decline precision | **1.000** (no declined case had a right-leaning judgment underneath) |
| Reviewer downgrades | 9,567/10,359 concluded (92.35%; they hit correct conclusions, 94.68%, more often than wrong ones, 65.11% — see report) |
| Agent analyses executed | 83,226, zero failed or timed out |

## Pipeline

```
planner -> gather_clinvar -> gather_gnomad -> gather_pubmed
        -> compute -> judge -> decline_gate -> reviewer
        -> experiment_designer -> dossier_writer  (LangGraph)
```

- **Planner** — resolves the variant against the local
  vus-evidence-agent tables and writes the investigation plan
  (LLM when an endpoint answers, deterministic template otherwise).
- **Gatherers** — ClinVar frozen status + AlphaMissense + REVEL +
  gene prior from the LOCAL processed data (no scraping); gnomAD via
  its public GraphQL API (live) or the recorded lookup (offline);
  PubMed via E-utilities (live only). Every item carries a source
  identifier.
- **Compute** — the agent generates small Python analyses
  (population context, predictor agreement, score percentiles) and
  executes them in a no-network sandbox (separate process, scrubbed
  environment, 30 s timeout, resource limits). An analysis becomes a
  cited evidence item only when it runs cleanly and computes real
  content; failures and empty results are shown in the dossier but
  never count toward the decline gate. A reachable LLM may propose a
  script body instead (same sandbox, screened first, template
  fallback).
- **Judge** — the calibrated GBM+R probability recorded by
  vus-evidence-agent (MODEL_REPORT_6: AUROC 0.9705, ECE 0.0248,
  Brier 0.0625 on the full temporal test set). Variants the model
  never scored fall back to a transparent, labelled evidence score —
  never dressed up as a probability.
- **Decline gate** — fewer than 3 independent evidence items, or an
  indeterminate judgment, produces a DECLINED dossier that names the
  missing evidence.
- **Reviewer** — deterministic adversarial critique: evidence
  independence (correlated predictors, the model probability's own
  inputs, analyses derived from other items), direction conflicts,
  missing evidence classes, calibration caveats, and strength vs
  independent support. A material finding downgrades the confidence
  language one step (strong → moderate → weak); the reviewer can
  never upgrade, change the lean, or reverse a decline. An LLM
  critique may be appended, labelled and advisory.
- **Experiment designer** — for every case, concluded or DECLINED,
  proposes ordered validation experiments matched to the variant
  class and the missing evidence classes, each stating in advance
  which result supports pathogenic and which supports benign.
- **Dossier writer** — Markdown dossier + JSON trace: verdict,
  judgment basis, fully cited evidence table, the agent's analyses
  with script hashes, reviewer critique, experiment designs,
  missing-evidence and provenance sections.

## The honesty rules (BUILD_PLAN.md R1–R5)

- **R1 Temporal integrity** — only prediction-time (frozen 2024-01)
  records are evidence. The later ClinVar reclassification is never
  loaded into the pipeline (the data layer's column whitelist makes
  this structural, not a promise). The benchmark reads it only to
  stratify the sample and to score finished dossiers.
- **R2 No source, no claim** — every evidence item carries a source
  identifier; the dossier cites it.
- **R3 Decline is a first-class output** — below the bar, the dossier
  says so and names what evidence is missing.
- **R4 No invented numbers** — every quantity comes from local data,
  a recorded model run, a live lookup, or a sandboxed computation
  over those.
- **R5 Provider-agnostic LLM** — any OpenAI-compatible endpoint via
  env; the whole pipeline also runs fully offline with no LLM key,
  deterministically.

## Setup

```bash
cd ~/workspace/variant-research-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # + pytest to run the tests
```

The agent reads the source project's data in place
(`~/workspace/vus-evidence-agent`, override with `VRA_VUS_HOME`).
Nothing is copied and the source projects are never modified.

## Run it

Offline mode (default) — fully deterministic, no network, no LLM.
This is the reproducible mode, and the mode the benchmark used:

```bash
PYTHONPATH=src .venv/bin/python -m variant_research_agent "ARSB:c.1178A>C" --offline
PYTHONPATH=src .venv/bin/python -m variant_research_agent "allele:20309"
PYTHONPATH=src .venv/bin/python -m variant_research_agent "5:78839391:T>G"
```

Accepted variant forms: ClinVar allele id (`15925` / `allele:15925`),
`GENE:c.change`, `chr:pos:ref>alt` (GRCh38), or a substring of the
ClinVar name.

Live gatherers (gnomAD GraphQL + PubMed E-utilities, both free
public APIs) — recorded-lookup fallback if a call fails:

```bash
PYTHONPATH=src .venv/bin/python -m variant_research_agent "ARSB:c.1178A>C" --live
```

LLM mode — provider-agnostic, OpenAI-compatible. When an endpoint
answers, the planner, script proposals, reviewer note, and dossier
narrative use it; when it does not, everything degrades to the
deterministic path and the run is identical to offline mode:

```bash
export LLM_BASE_URL=http://localhost:8080/v1   # default — e.g. a local Hyperspace node
export LLM_API_KEY=...                          # only if the endpoint needs one
export LLM_MODEL=...                            # default "default"
PYTHONPATH=src .venv/bin/python -m variant_research_agent "ARSB:c.1178A>C"
```

`VRA_OFFLINE=1` (or `--offline`) forces template mode.

## Benchmark

```bash
.venv/bin/python scripts/benchmark.py --n 300 --seed 20261030
```

Writes `benchmark/sample.json` (frame + sampled ids),
`benchmark/results.jsonl`, `benchmark/summary.json`, and the 300
dossiers under `benchmark/dossiers/`. Methods and findings:
BENCHMARK_REPORT.md.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
```

Schema validation, decline-gate behaviour, end-to-end offline runs
on real variants, live gatherers with HTTP mocked (tests never touch
the network), the sandbox (network blocking, timeout kill, failure
recording), compute-stage evidence rules, reviewer
conflict/downgrade behaviour and the never-upgrade guarantee,
declined-case design, and unit tests for every benchmark metric.

## Worked examples

`examples/` holds three dossiers regenerated with the full pipeline:
[ARSB c.1178A>C](examples/example_dossier_pathogenic_ARSB.md)
(pathogenic-leaning, P = 0.989 — reviewer downgraded strong →
moderate: its directional support comes from one correlated
predictor family), [NHERF1 c.328C>G](examples/example_dossier_benign_NHERF1.md)
(benign-leaning, P = 0.012, strong stands — two independent families
support it), and [RYR1 c.14761_14762delinsAC](examples/example_dossier_declined_RYR1.md)
(DECLINED — 1 evidence item; the experiment design is the
deliverable). Phase reports: PHASE1_REPORT.md, PHASE2_REPORT.md,
PHASE3_REPORT.md, BENCHMARK_REPORT.md.

## Web app

`space/` contains a Hugging Face Space skeleton (Gradio) wrapping
the pipeline for one variant, offline mode by default. It is
**prepared, not deployed** — its app.py documents the data and
configuration a deployment must satisfy first.
