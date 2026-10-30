# Variant Research Dossier — NM_000046.5(ARSB):c.1178A>C (p.His393Pro)

**Gene:** ARSB  
**Genomic (GRCh38):** 5:78839391 T>G  
**ClinVar allele ID:** 15925  
**Local record:** processed_v3/test_features (vus-evidence-agent processed data)

## Verdict

**Evidence summary — moderate pathogenic-leaning** (not a clinical classification).

Calibrated P(pathogenic) = 0.989 from the GBM+R model (vus-evidence-agent MODEL_REPORT_6: AUROC 0.9705, ECE 0.0248, Brier 0.0625, temporal test set).

**Reviewer downgrade:** the reviewer reduced the confidence language from **strong** to **moderate** (material critique(s): strength_thin_independent_support). The lean and the probability are unchanged — the reviewer may only weaken confidence language, never strengthen it, and it cannot change the verdict's direction or the gate outcome.

## Judgment basis

- GBM+R isotonic-calibrated P(pathogenic) = 0.989 (GBM+R (gradient boosting + REVEL, isotonic calibrated); recorded run, data/processed_v2/MODEL_REPORT_6.md: AUROC 0.9705, ECE 0.0248, Brier 0.0625 on the temporal test set)

## Evidence (every claim cited)

| # | Source | Record | Detail | Direction |
|---|--------|--------|--------|-----------|
| 1 | ClinVar (frozen 2024-01) | CLINVAR:allele15925 | ClinVar status at the 2024-01 freeze: Conflicting interpretations of pathogenicity | neutral |
| 2 | AlphaMissense | AM:5:78839391:T>G | AlphaMissense score=0.709 class=likely_pathogenic | pathogenic |
| 3 | REVEL (Zenodo 7072866) | REVEL:5:78839391:T>G | REVEL score=0.906 | pathogenic |
| 4 | Gene prior (frozen train) | GENEPRIOR:ARSB:frozen2024 | gene=ARSB tranche=T1 (prior from frozen train labels only) | neutral |
| 5 | gnomAD (recorded lookup, local data) | GNOMAD:5:78839391:T>G | gnomAD allele frequency = 7.66e-05 | neutral |
| 6 | Agent analysis: population_context | ANALYSIS:population_context:feb9091c172e | gnomAD AF 7.66e-05 is at the 83.3th percentile of the 18225 recorded gnomAD frequencies in the local temporal test set (median 1.23e-05); rarity class: rare (AF < 0.001). | neutral |
| 7 | Agent analysis: predictor_agreement | ANALYSIS:predictor_agreement:8a007a8ba774 | Predictor agreement over 3 predictors: 3 pathogenic lean(s), 0 benign, 0 indeterminate; pairwise agreement 3/3 pairs; consensus: pathogenic (unanimous). | neutral |
| 8 | Agent analysis: score_percentiles | ANALYSIS:score_percentiles:aea82dea4c2d | AlphaMissense 0.709 is at the 62.8th percentile of the local test-set AlphaMissense distribution (n=10373); REVEL 0.906 is at the 82.8th percentile of the local test-set REVEL distribution (n=11023). | neutral |

## Analyses run by the agent

Each analysis below is a Python script the agent generated and executed in a no-network sandbox (30 s timeout). Script sources and full outputs are in the JSON trace. Only analyses with real computed content count as evidence; failures are shown, never hidden.

- **population_context** [template script, sha feb9091c172e, 0.07s] — status: **ok**
  - gnomAD AF 7.66e-05 is at the 83.3th percentile of the 18225 recorded gnomAD frequencies in the local temporal test set (median 1.23e-05); rarity class: rare (AF < 0.001).
  - Counted as evidence: <ANALYSIS:population_context:feb9091c172e>
- **predictor_agreement** [template script, sha 8a007a8ba774, 0.05s] — status: **ok**
  - Predictor agreement over 3 predictors: 3 pathogenic lean(s), 0 benign, 0 indeterminate; pairwise agreement 3/3 pairs; consensus: pathogenic (unanimous).
  - Counted as evidence: <ANALYSIS:predictor_agreement:8a007a8ba774>
- **score_percentiles** [template script, sha aea82dea4c2d, 0.08s] — status: **ok**
  - AlphaMissense 0.709 is at the 62.8th percentile of the local test-set AlphaMissense distribution (n=10373); REVEL 0.906 is at the 82.8th percentile of the local test-set REVEL distribution (n=11023).
  - Counted as evidence: <ANALYSIS:score_percentiles:aea82dea4c2d>

## Reviewer critique

An adversarial reviewer stage checked this draft deterministically: evidence independence, direction conflicts, missing evidence classes, calibration caveats, and whether the verdict strength matches its independent support. Severity: **material** findings can downgrade the confidence language one step; **notable** findings are real weaknesses the reader must see; **minor** findings are context. The reviewer can never upgrade a verdict or reverse a decline.

- Independent evidence families present: frozen ClinVar record, gene prior, in-silico missense predictors, population frequency (gnomAD) (4)
- **[notable] independence_predictor_correlation** — AlphaMissense and REVEL (Zenodo 7072866) are both in-silico missense predictors trained on overlapping variant corpora and conservation signal — their agreement is one correlated observation, not two independent ones.
- **[notable] independence_derivative_analyses** — 3 of the 8 evidence items are agent analyses computed FROM other items in this same dossier (population context from the gnomAD item; agreement and percentile statistics from the predictor items). They add computed context, not independent observations. Effective independent evidence families: frozen ClinVar record, gene prior, in-silico missense predictors, population frequency (gnomAD) (4).
- **[notable] independence_model_features** — The GBM+R probability anchoring this verdict is itself computed from REVEL (Zenodo 7072866) and Gene prior (frozen train) (data/processed_v2/MODEL_REPORT_6.md). Citing the probability AND those items as separate support double-counts one signal chain.
- **[notable] conflict_within_clinvar** — The frozen ClinVar record itself reads 'Conflicting interpretations of pathogenicity': submitters disagreed at the 2024-01 freeze, so the ClinVar item is neutral context, not support for either side.
- **[notable] missing_functional** — No functional/experimental evidence: no assay has measured what this variant does to the gene product.
- **[notable] missing_segregation** — No segregation evidence: no family data shows whether the variant tracks with disease.
- **[minor] missing_literature** — No literature evidence: no published article on this exact variant is in this dossier.
- **[notable] caveat_calibration_scope** — The probability is a RECORDED output of the GBM+R run, which scored 10,357 of the 27,748 temporal test variants. Its calibration (ECE 0.0248, AUROC 0.9705) was measured on that test set as a whole — per-gene and per-consequence calibration is unknown, so the probability is a set-level calibrated estimate, not a variant-specific guarantee.
- **[minor] caveat_percentile_reference** — Percentile context in this dossier is computed against the local temporal test set, which is enriched for variants that were later reclassified. These are percentiles within that enriched set, not population percentiles.
- **[material] strength_thin_independent_support** — Strength challenge: the 'strong' pathogenic language rests on directional support from 1 independent evidence family (in-silico missense predictors). Correlated items count once. One family is not enough to carry 'strong'.
- **Downgrade applied:** strong → moderate (material critique(s): strength_thin_independent_support).

## Validation experiment design

Experiments that would most efficiently settle this variant, in priority order. They target the evidence classes this verdict does NOT rest on; for each, the result that would support pathogenic and the result that would support benign are stated in advance.

**1. Functional assay of the ARSB gene product (cellular model expressing variant vs wild-type)**

- Supplies: functional evidence, a class entirely absent from this dossier
- Why this experiment: This is a missense variant in ARSB; the decisive unknown is what the change does to the gene product's activity, stability, or interaction behaviour. A controlled variant-vs-wild-type assay measures exactly that, and no functional evidence of any kind is in this dossier.
- Result supporting pathogenic: Variant protein activity, stability, or localisation significantly outside the wild-type range across replicates, in the direction of the gene's known disease mechanism.
- Result supporting benign: Variant protein measures within the wild-type range across replicates on every readout.

**2. Segregation analysis (genotype affected and unaffected relatives)**

- Supplies: segregation evidence, a class entirely absent from this dossier
- Why this experiment: No family data exists for this variant. Co-segregation is evidence of a different KIND from every predictor and frequency item in this dossier — it observes the variant in patients, not in a model — so it adds a genuinely independent observation.
- Result supporting pathogenic: The variant co-segregates with the phenotype: present in affected relatives and absent from unaffected relatives, consistent with the gene's inheritance model.
- Result supporting benign: Non-segregation: an affected relative who does not carry the variant, or unaffected carriers at a rate the inheritance model cannot accommodate.

**3. Case aggregation (published case series, ClinVar submitter detail, matchmaking exchange)**

- Supplies: literature evidence (published data on this exact variant)
- Why this experiment: No published case data on this exact variant is in the dossier. Aggregating independent probands converts an anecdote into a countable observation and is often what moves a VUS re-review.
- Result supporting pathogenic: Multiple unrelated affected probands carry the variant with a consistent phenotype, while it stays absent from control cohorts.
- Result supporting benign: Reports of the variant in unaffected individuals, or in probands whose phenotype is fully explained by another cause.


## Run notes

- PubMed not queried (offline mode) — literature evidence not counted in this run

## Narrative

Retrieved 8 independent evidence item(s) for NM_000046.5(ARSB):c.1178A>C (p.His393Pro). ClinVar (frozen 2024-01): ClinVar status at the 2024-01 freeze: Conflicting interpretations of pathogenicity <CLINVAR:allele15925>. AlphaMissense: AlphaMissense score=0.709 class=likely_pathogenic <AM:5:78839391:T>G>. REVEL (Zenodo 7072866): REVEL score=0.906 <REVEL:5:78839391:T>G>. Gene prior (frozen train): gene=ARSB tranche=T1 (prior from frozen train labels only) <GENEPRIOR:ARSB:frozen2024>. gnomAD (recorded lookup, local data): gnomAD allele frequency = 7.66e-05 <GNOMAD:5:78839391:T>G>. Agent analysis: population_context: gnomAD AF 7.66e-05 is at the 83.3th percentile of the 18225 recorded gnomAD frequencies in the local temporal test set (median 1.23e-05); rarity class: rare (AF < 0.001). <ANALYSIS:population_context:feb9091c172e>. Agent analysis: predictor_agreement: Predictor agreement over 3 predictors: 3 pathogenic lean(s), 0 benign, 0 indeterminate; pairwise agreement 3/3 pairs; consensus: pathogenic (unanimous). <ANALYSIS:predictor_agreement:8a007a8ba774>. Agent analysis: score_percentiles: AlphaMissense 0.709 is at the 62.8th percentile of the local test-set AlphaMissense distribution (n=10373); REVEL 0.906 is at the 82.8th percentile of the local test-set REVEL distribution (n=11023). <ANALYSIS:score_percentiles:aea82dea4c2d>. Gate outcome: conclusion permitted.

## Provenance

- Plan mode: template; LLM mode: offline
- Gatherers: ClinVar (local processed data), gnomAD (recorded lookup), PubMed (not queried — offline)
- Compute stage: 3 agent analyses executed in a no-network sandbox (30 s timeout); script sources + outputs are in the JSON trace.
- Reviewer stage: deterministic critique, 10 finding(s); downgrade applied: yes; LLM critique: absent.
- Experiment designer: 3 validation experiment design(s) proposed.
- Temporal integrity (R1): only prediction-time (frozen 2024-01) records were used as evidence; the later ClinVar reclassification was never loaded.
- Not for clinical use. Research project only.
