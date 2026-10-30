# Phase 1 Report — Variant Research Agent (fusion)

Built 2026-10-30. Phase 1 of BUILD_PLAN.md: LangGraph pipeline
(planner → gatherers → judge → decline gate → dossier), CLI,
offline-deterministic mode, tests. Nothing in the three source
projects was modified; their data is read in place.

## What was built

```
src/variant_research_agent/
  schema.py     pydantic EvidenceItem / VariantRecord / Judgment / GateResult
  data.py       local-table access + variant resolution (allele id,
                GENE:c.change, chr:pos:ref>alt, name substring)
  llm.py        provider-agnostic OpenAI-compatible client (env config)
  gatherers.py  ClinVar local / gnomAD / PubMed gatherers
  model.py      GBM+R adapter over the recorded predictions + stub
  judge.py      model-probability judgment, evidence-scoring fallback
  graph.py      the LangGraph pipeline + events accounting
  dossier.py    Markdown dossier + JSON trace writer
  __main__.py   CLI: python -m variant_research_agent <variant>
tests/          17 tests, all passing (schema, gate, end-to-end
                offline, live gatherers with HTTP mocked)
runs/           the 3 worked-example dossiers + traces (copies in examples/)
```

## How each stage works

- **Planner** resolves the query against the local tables (v3 test
  features first, then v2 test, then the frozen train table) and
  writes the investigation plan — by LLM when an endpoint answers,
  else a deterministic template that adapts to the variant (e.g. it
  notes missense consequence). Only prediction-time columns are ever
  loaded: the resolver's column whitelist does not include sig_now /
  label, so the future reclassification cannot leak into evidence
  (R1 enforced structurally, not by discipline).
- **Gatherers** port vus-evidence-agent's `build_v3` evidence logic:
  frozen ClinVar status (always exactly one item), AlphaMissense and
  REVEL as separate cited items (REVEL direction uses the Pejaver
  2022 thresholds 0.644 / 0.290), a gene-prior item when a tranche
  ensemble probability exists, and a gnomAD item only when a lookup
  actually happened (an AF value, or a retrieved "not observed"
  record; status "unknown" yields no item). Live mode queries the
  gnomAD GraphQL API (gnomad_r4) and PubMed E-utilities; on any live
  failure the gnomAD gatherer falls back to the recorded lookup and
  logs it in the run notes. PubMed items are direction-neutral by
  design: literature existence is context, not evidence of effect.
- **Judge** uses the GBM+R adapter (below). Without a recorded
  probability it falls back to a transparent signed direction sum
  (pathogenic +1 / benign −1), labelled everywhere as NOT a
  calibrated probability; |score| < 2 is "indeterminate".
- **Decline gate** (deterministic, in code): < 3 independent items →
  DECLINED with the missing evidence named; indeterminate judgment →
  DECLINED. Otherwise the dossier concludes with an evidence summary
  (never worded as a clinical classification).
- **Dossier writer** renders the verdict, judgment basis, a fully
  cited evidence table, missing-evidence and provenance sections, and
  a narrative — extractive template offline; in LLM mode the model
  writes the narrative from the evidence items only and cannot alter
  the verdict, numbers, or table.

## The model: loaded, with one honest stub

There is **no serialised model artifact** in vus-evidence-agent (no
.pkl / .joblib anywhere). What exists is the adopted model's recorded
output: `data/processed_v2/test_predictions_trees.csv` from the
MODEL_REPORT_6 run (GBM + REVEL + isotonic; AUROC 0.9705, ECE 0.0248,
Brier 0.0625). `model.CalibratedModelAdapter.predict_recorded()`
loads exactly those probabilities — every number in every dossier is
a real output of that real run (R4). Coverage: 10,357 of the 27,748
temporal-test variants have a recorded probability.

`predict_fresh()` is a clearly marked **adapter stub** that raises
NotImplementedError: scoring a brand-new variant would require
retraining GBM+R on the frozen train split via the source project's
`scripts/train_trees.py` (Phase 2 candidate). Until then, variants
without a recorded probability are judged by the evidence-scoring
fallback, and the dossier says so.

## What was reused from each source project

- **vus-evidence-agent** — the temporal-split data itself; the
  `build_v3` evidence-item logic and record-id conventions
  (AM:/REVEL:/GNOMAD:/CLINVAR:/GENEPRIOR:); MIN_EVIDENCE = 3 and the
  cite-or-decline rule; the GBM+R recorded predictions and
  MODEL_REPORT_6 metrics; the "evidence summary (not a clinical
  classification)" wording.
- **multi-agent-evidence** — the LangGraph state-graph shape, the
  events-accounting pattern (every stage logs what it did), the rule
  that deterministic code, not the LLM, enforces the gate, and the
  "log LLM failures, never swallow them" discipline in llm.py.
- **hybrid-perturb-bench** — evaluation discipline: fixed example set
  chosen from the data with declared criteria, mocked-network tests,
  and this report's insistence that every reported number was
  produced by a recorded run.

## The 3 worked examples (offline mode, `runs/`)

| Variant | Evidence items | Judgment | Outcome |
|---|---|---|---|
| ARSB NM_000046.5:c.1178A>C (p.His393Pro), allele 15925 | 5 | GBM+R P(pathogenic) = 0.989 | **Strong pathogenic-leaning summary.** AM 0.709 (likely_pathogenic) and REVEL 0.906 agree; gnomAD AF 7.66e-05. (ClinVar later reclassified it Pathogenic/Likely pathogenic — evaluation-only, never used as evidence.) |
| NHERF1 NM_004252.5:c.328C>G (p.Leu110Val), allele 20309 | 5 | GBM+R P(pathogenic) = 0.012 | **Strong benign-leaning summary.** AM 0.095, REVEL 0.070, gnomAD AF 0.0263 (common). Later reclassified Benign/Likely benign. |
| RYR1 NM_000540.3:c.14761_14762delinsAC (p.Phe4921Thr), allele 28034 | 1 | evidence scoring, +0 (indeterminate) | **DECLINED — insufficient evidence, remains VUS.** A delins that was a VUS at the freeze: no missense predictor scores exist, no gnomAD lookup was recorded, no GBM+R probability. The dossier names the missing evidence (predictor scores, a gnomAD lookup, literature). |

Live-mode smoke test (not in `runs/`): with `--live`, the gnomAD
GraphQL gatherer returned AF 7.66e-05 for the ARSB variant, exactly
matching the recorded lookup — a genuine cross-check of both paths.
(One real bug was found and fixed during this test: the GraphQL
argument is `variantId`, not `variant_id`.) With LLM_BASE_URL
pointed at a dead port, the pipeline degraded to offline templates
and produced an identical verdict, as designed.

## Known limitations

- Recorded GBM+R probabilities cover only the 10,357 test variants
  the source model scored; everything else uses the uncalibrated
  evidence-scoring fallback (or declines).
- Resolution is limited to variants present in the local tables
  (temporal test set + frozen train set). A variant outside them
  raises a clear "not found" error — by design for Phase 1, since
  live ClinVar retrieval belongs to a later phase.
- PubMed search is a simple gene + protein-change query; it can miss
  literature that names a variant differently, and in offline mode
  literature never counts toward the gate.
- The gene-prior item counts toward the 3-item bar, matching
  vus-evidence-agent's v3 logic; whether a prior should count as
  "independent evidence" is a Phase 4 benchmark question.
- LLM mode is implemented and degrades correctly, but no live LLM
  endpoint was available in this environment (localhost:8080 did not
  answer), so LLM-written plans/narratives are untested against a
  real model. The deterministic path is fully tested.
- No compute stage yet (Phase 2), no critic/experiment-designer
  (Phase 3), no benchmark (Phase 4) — per the build plan.
