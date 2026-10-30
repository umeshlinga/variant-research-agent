# Variant Research Dossier — NM_000540.3(RYR1):c.14761_14762delinsAC (p.Phe4921Thr)

**Gene:** RYR1  
**Genomic (GRCh38):** 19:38585057 TT>AC  
**ClinVar allele ID:** 28034  
**Local record:** processed_v3/test_features (vus-evidence-agent processed data)

## Verdict

**DECLINED — insufficient evidence — remains VUS.**

The decline gate refused to conclude: evidence below the cite-or-decline bar (1 independent evidence item(s), minimum 3).

## Judgment basis

- No recorded GBM+R probability exists for this variant (adapter stub: the source project ships no serialised model), so judgment falls back to transparent evidence scoring: signed direction sum = +0 over 1 item(s). This is NOT a calibrated probability.

## Evidence (every claim cited)

| # | Source | Record | Detail | Direction |
|---|--------|--------|--------|-----------|
| 1 | ClinVar (frozen 2024-01) | CLINVAR:allele28034 | ClinVar status at the 2024-01 freeze: Uncertain significance | neutral |

## Analyses run by the agent

Each analysis below is a Python script the agent generated and executed in a no-network sandbox (30 s timeout). Script sources and full outputs are in the JSON trace. Only analyses with real computed content count as evidence; failures are shown, never hidden.

- **population_context** [template script, sha feb9091c172e, 0.07s] — status: **no_content**
  - No gnomAD allele frequency is available for this variant (no recorded or live frequency), so population context cannot be computed.
  - Not counted as evidence (no computed content — a needed datum was unavailable).
- **predictor_agreement** [template script, sha 8a007a8ba774, 0.06s] — status: **no_content**
  - Predictor agreement needs at least 2 predictors; only 0 available for this variant (none), so no agreement statistic is computed.
  - Not counted as evidence (no computed content — a needed datum was unavailable).
- **score_percentiles** [template script, sha aea82dea4c2d, 0.07s] — status: **no_content**
  - no AlphaMissense score exists for this variant; no REVEL score exists for this variant.
  - Not counted as evidence (no computed content — a needed datum was unavailable).

## Reviewer critique

An adversarial reviewer stage checked this draft deterministically: evidence independence, direction conflicts, missing evidence classes, calibration caveats, and whether the verdict strength matches its independent support. Severity: **material** findings can downgrade the confidence language one step; **notable** findings are real weaknesses the reader must see; **minor** findings are context. The reviewer can never upgrade a verdict or reverse a decline.

This case was DECLINED by the gate. The reviewer has no power to reverse a decline (R3) and records it as upheld; the critiques below explain the evidence state the decline rests on.

- Independent evidence families present: frozen ClinVar record (1)
- **[notable] missing_functional** — No functional/experimental evidence: no assay has measured what this variant does to the gene product.
- **[notable] missing_segregation** — No segregation evidence: no family data shows whether the variant tracks with disease.
- **[notable] missing_population** — No population-frequency evidence: no successful gnomAD lookup exists for this variant, so rarity is unmeasured.
- **[notable] missing_predictors** — No missense predictor scores: neither AlphaMissense nor REVEL has a score for this variant in the local data.
- **[minor] missing_literature** — No literature evidence: no published article on this exact variant is in this dossier.
- **[notable] caveat_uncalibrated_judgment** — No recorded GBM+R probability exists for this variant (outside the model's recorded coverage), so the judgment is an uncalibrated signed sum of evidence directions — a transparency device, not a probability.

## Validation experiment design

The gate declined for insufficient evidence. These are the experiments that would most efficiently supply what is missing, in priority order — for each, the result that would support pathogenic and the result that would support benign are stated in advance.

**1. Deeper population-frequency data (current gnomAD release + ancestry-matched control cohorts)**

- Supplies: the missing population-frequency evidence (a successful gnomAD-scale lookup)
- Why this experiment: No successful gnomAD lookup exists for this in-frame delins (length-preserving residue change) variant in RYR1, so its rarity — the cheapest decisive fact about a candidate disease variant — is unmeasured. A current-release lookup with ancestry-matched cohorts is the fastest first step to break the decline.
- Result supporting pathogenic: The variant remains absent, or orders of magnitude rarer than known benign polymorphisms, in ancestry-matched controls at a scale where a neutral variant would be expected to appear.
- Result supporting benign: An allele frequency comparable to known benign polymorphisms — far too common for a penetrant disease allele in this gene — in any well-sampled ancestry group.

**2. Functional assay of the RYR1 gene product (cellular model expressing variant vs wild-type)**

- Supplies: functional evidence, a class entirely absent from this dossier
- Why this experiment: This is an in-frame delins (length-preserving residue change) variant in RYR1; the decisive unknown is what the change does to the gene product's activity, stability, or interaction behaviour. A controlled variant-vs-wild-type assay measures exactly that, and no functional evidence of any kind is in this dossier.
- Result supporting pathogenic: Variant protein activity, stability, or localisation significantly outside the wild-type range across replicates, in the direction of the gene's known disease mechanism.
- Result supporting benign: Variant protein measures within the wild-type range across replicates on every readout.

**3. Segregation analysis (genotype affected and unaffected relatives)**

- Supplies: segregation evidence, a class entirely absent from this dossier
- Why this experiment: No family data exists for this variant. Co-segregation is evidence of a different KIND from every predictor and frequency item in this dossier — it observes the variant in patients, not in a model — so it adds a genuinely independent observation.
- Result supporting pathogenic: The variant co-segregates with the phenotype: present in affected relatives and absent from unaffected relatives, consistent with the gene's inheritance model.
- Result supporting benign: Non-segregation: an affected relative who does not carry the variant, or unaffected carriers at a rate the inheritance model cannot accommodate.

**4. Case aggregation (published case series, ClinVar submitter detail, matchmaking exchange)**

- Supplies: literature evidence (published data on this exact variant)
- Why this experiment: No published case data on this exact variant is in the dossier. Aggregating independent probands converts an anecdote into a countable observation and is often what moves a VUS re-review.
- Result supporting pathogenic: Multiple unrelated affected probands carry the variant with a consistent phenotype, while it stays absent from control cohorts.
- Result supporting benign: Reports of the variant in unaffected individuals, or in probands whose phenotype is fully explained by another cause.


## Missing evidence (what would be needed)

- a precomputed missense predictor score (AlphaMissense)
- a REVEL predictor score
- a successful gnomAD population-frequency lookup
- published literature on this exact variant (PubMed)

## Run notes

- gnomAD: no successful lookup recorded for this allele (status unknown) — no gnomAD evidence item
- PubMed not queried (offline mode) — literature evidence not counted in this run

## Narrative

Retrieved 1 independent evidence item(s) for NM_000540.3(RYR1):c.14761_14762delinsAC (p.Phe4921Thr). ClinVar (frozen 2024-01): ClinVar status at the 2024-01 freeze: Uncertain significance <CLINVAR:allele28034>. Gate outcome: DECLINED — insufficient evidence — remains VUS.

## Provenance

- Plan mode: template; LLM mode: offline
- Gatherers: ClinVar (local processed data), gnomAD (recorded lookup), PubMed (not queried — offline)
- Compute stage: 3 agent analyses executed in a no-network sandbox (30 s timeout); script sources + outputs are in the JSON trace.
- Reviewer stage: deterministic critique, 6 finding(s); downgrade applied: no; LLM critique: absent.
- Experiment designer: 4 validation experiment design(s) proposed.
- Temporal integrity (R1): only prediction-time (frozen 2024-01) records were used as evidence; the later ClinVar reclassification was never loaded.
- Not for clinical use. Research project only.
