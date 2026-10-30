# Phase 3 Report — Reviewer (critique) + experiment designer

Phase 3 adds the two stages BUILD_PLAN.md calls CRITIQUE and DESIGN,
between the decline gate and the dossier writer:

```
planner -> gather_clinvar -> gather_gnomad -> gather_pubmed
        -> compute -> judge -> decline_gate
        -> reviewer -> experiment_designer -> dossier_writer
```

All work is inside this project; the three source projects are
untouched and their data is read in place (R1 preserved).

## What was built

### New modules

- `src/variant_research_agent/reviewer.py` — the adversarial
  reviewer. Deterministic checks over the real evidence items, the
  Phase 2 computed analyses, the judgment, and the gate result.
  Optional LLM critique appended when an endpoint answers: stored
  separately, labelled advisory, and structurally unable to change
  the deterministic outcome (a test proves the downgrade decision is
  identical with and without a fake LLM supplying text).
- `src/variant_research_agent/designer.py` — the rule-based
  experiment designer. Proposes ordered validation experiments from
  the variant class (VEP consequence / name patterns in the local
  record), the gene, and the missing evidence classes. Optional LLM
  note, same labelled pattern.

### Schema / wiring / dossier changes

- `schema.py`: `CritiqueItem`, `Review`, `ExperimentDesign`.
- `graph.py`: `reviewer` and `experiment_designer` nodes after
  `decline_gate`; state gains `review` and `design`; the planner's
  template (and the LLM planner prompt) now name both stages.
- `dossier.py`: dossier v2 gains "Reviewer critique" and
  "Validation experiment design" sections; a "Reviewer downgrade"
  note in the Verdict section when one is applied; reviewer/designer
  lines in Provenance; the JSON trace gains `review` and `design`
  keys (critique items, downgrade record, all designs).
- `__main__.py`: CLI prints a review line (critique count, material
  count, downgrade) and a designs line.

## The reviewer's powers — deliberately narrow

- It may DOWNGRADE the judgment's confidence language exactly one
  step (strong -> moderate -> weak) when a MATERIAL critique exists.
- It may never upgrade, never change the lean, basis, probability, or
  evidence, and never resurrect a DECLINED case: the gate result is
  read-only input, and for a declined case the review records
  `decline_upheld` and leaves the judgment untouched. Both guarantees
  are enforced by construction (the reviewer returns a copied
  judgment with only `strength` changed, and only on the gate-passed
  path) and pinned by tests.

## The critique taxonomy

Severities: **material** (can force the one-step downgrade),
**notable** (a real weakness the reader must see), **minor**
(context). Every finding is computed from this run's own items (R4)
and names the items it is about (R2).

(a) **Evidence independence** — items are mapped to families
(frozen ClinVar record, in-silico missense predictors, gene prior,
population frequency, literature, agent analyses). Checks:
`independence_predictor_correlation` (AlphaMissense + REVEL share
training signal — notable), `independence_derivative_analyses`
(counted ANALYSIS items are computed FROM other dossier items, so
the evidence "count" overstates independence; the effective family
list is printed — notable), `independence_model_features` (the GBM+R
probability is itself a function of the REVEL item and the gene
prior — notable).

(b) **Direction conflicts** — `direction_conflict` (directional
gathered items lean both ways — MATERIAL), `conflict_within_clinvar`
(the frozen record itself reads "Conflicting interpretations…" —
notable), `conflict_predictor_split` (the agent's own agreement
analysis reports a split consensus — MATERIAL) /
`conflict_predictor_disagreement` (pairwise agreement < 1.0 —
notable), `conflict_model_vs_evidence_sum` (the transparent evidence
sum contradicts the model lean — MATERIAL; or sums to indeterminate
under a strong model verdict — notable).

(c) **Missing evidence classes** — `missing_functional`,
`missing_segregation`, `missing_population`, `missing_predictors`
(all notable), `missing_literature` (minor). Detection is by source
family, so a class stops being flagged the moment a real item of
that family exists.

(d) **Calibration caveats** — `caveat_calibration_scope` (the
probability is a recorded output over 10,357 of 27,748 test
variants; ECE/AUROC are set-level, per-gene calibration unknown —
notable), `caveat_uncalibrated_judgment` (evidence-scoring basis —
notable), `caveat_percentile_reference` (percentiles are within the
reclassification-enriched test set, not population percentiles —
minor, fires when a percentile analysis produced content).

(e) **Strength vs support** — `strength_thin_independent_support`
(MATERIAL): a concluded GBM+R verdict whose directional support
comes from fewer than two independent evidence FAMILIES is
challenged — correlated items count once, so two agreeing missense
predictors are one family, not two.

## The designer's rules

Designs are ordered by expected information per unit effort given
what is missing:

1. **Deeper population-frequency data** (current gnomAD release +
   ancestry-matched cohorts) — only when no gnomAD item exists;
   cheapest and often decisive.
2. **Functional readout matched to the variant class** — an
   RNA/splicing assay (minigene or patient-RNA RT-PCR) for
   splice-region variants; a variant-vs-wild-type functional assay
   of the gene product otherwise (missense, in-frame delins,
   frameshift, stop-gain).
3. **Segregation analysis** — always proposed (the class is always
   absent with the current gatherers); it is the one design that
   adds a wholly independent evidence KIND.
4. **Case aggregation** — only when no literature item exists.

Every design carries `supports_pathogenic` and `supports_benign`
stated in advance, plus `supplies` naming the missing evidence class
it would fill. For DECLINED cases the design block is framed as the
deliverable; for concluded cases it targets the classes the verdict
does not rest on.

## What the reviewer found in the 3 examples (offline, regenerated)

### ARSB c.1178A>C — DOWNGRADED strong -> moderate (10 critiques, 1 material)

The material finding is `strength_thin_independent_support`: every
directional item behind the "strong pathogenic" language sits in ONE
independent family — the in-silico missense predictors
(AlphaMissense 0.709 and REVEL 0.906, themselves flagged as
correlated). The gnomAD item is neutral (AF 7.66e-05), the ClinVar
item is neutral, the gene prior is neutral; the P = 0.989 itself is
computed FROM REVEL + the prior. NHERF1 below shows the asymmetry
the rule is designed to catch. Notable findings: predictor
correlation; 3 of 8 items are derivative analyses (4 effective
families, not 8); model-features double counting; the frozen ClinVar
record is itself "Conflicting interpretations"; no functional and
no segregation evidence; calibration-scope caveat. Minor: no
literature item; percentile-reference caveat. The probability, lean
and evidence are unchanged — only the confidence language moved.
Designs (3): ARSB functional assay, segregation, case aggregation.

### NHERF1 c.328C>G — strong stands (9 critiques, 0 material)

Same independence, ClinVar-conflict, missing-class and calibration
findings as ARSB (the structural weaknesses of this evidence stack
are shared), but NO material finding: the benign lean is
directionally supported by two independent families — the predictors
(AM 0.095, REVEL 0.070) AND population frequency (gnomAD AF 0.0263,
direction benign) — with unanimous computed agreement and a raw
evidence sum (-3) that matches the model. Designs (3): NHERF1
functional assay, segregation, case aggregation (no population
design — the gnomAD item exists).

### RYR1 c.14761_14762delinsAC — still DECLINED, design is the deliverable

Gate unchanged (1 evidence item). The reviewer's 6 critiques explain
the evidence state the decline rests on: missing functional,
segregation, population AND predictor classes, no literature, and
the uncalibrated-judgment caveat; `decline_upheld` is recorded and
the judgment is byte-identical to the judge's output. Four designs,
in order: (1) deeper population-frequency data — supplies the
missing gnomAD lookup; (2) functional assay of the RYR1 gene product
(the variant classifies as an in-frame, length-preserving delins);
(3) segregation analysis; (4) case aggregation.

## Tests

Full suite: **40 passed** (30 Phases 1–2 + 10 new), offline, no
network. New coverage in `tests/test_phase3.py`:

- reviewer flags a constructed conflicting-evidence case
  (AlphaMissense pathogenic vs gnomAD benign) as MATERIAL, naming
  both items;
- downgrade path: strong -> moderate (exactly one step even with two
  material critiques), recorded in the Review, input judgment not
  mutated, lean/basis/probability untouched;
- a split predictor-agreement analysis is flagged MATERIAL;
- never-upgrade battery: every strength x {conflicted, clean-ish}
  case never comes back stronger; a weak verdict stays weak;
- LLM critique is advisory only (fake client): identical
  deterministic outcome and critiques, text stored and labelled;
- designer ordering: population design first when gnomAD is missing;
  splice-region variant gets the RNA/splicing assay;
- end-to-end all three examples: ARSB downgraded in state, dossier
  and trace; NHERF1 strong stands with no material critique; RYR1
  stays DECLINED with `decline_upheld`, >= 3 designs, population
  design first, both new sections in the dossier and trace.

One Phase 1–2 behaviour changed deliberately: the ARSB dossier's
verdict language is now "moderate pathogenic-leaning" (the Phase 2
report recorded "strong"). No earlier test asserted the old word —
the Phase 3 e2e test asserts the new one, and the probability
(0.989) is asserted unchanged in the same test.

## Limitations — stated honestly

- A rule-based critique is not a scientist. The taxonomy checks
  structural properties of the evidence (families, directions,
  presence/absence, set-level calibration scope). It cannot judge
  whether a predictor is trustworthy FOR THIS GENE, whether a
  functional assay is feasible in a real lab, or whether the disease
  mechanism makes a frequency threshold sensible — the designs are
  template-level proposals with pre-stated outcomes, not protocols.
- The independence families are a coarse model: AlphaMissense and
  REVEL are treated as one family although they are not identical
  methods, and the gene prior is treated as its own family although
  it derives from ClinVar train labels. Phase 4's benchmark is the
  place to test whether these choices help or hurt.
- The downgrade rule is deliberately conservative (one step, only on
  material findings, only on calibrated-basis verdicts). It will
  miss soft overconfidence that a human reviewer would catch in
  prose — which is exactly the gap the optional LLM critique exists
  to narrow.
- The LLM critique and designer note are implemented and their
  plumbing is tested with a fake client, but — as in Phases 1–2 —
  no live LLM endpoint was reachable in this environment
  (localhost:8080 did not answer during the build), so LLM-written
  critique text is untested against a real model. That check belongs
  on the user's Mac with the Hyperspace node up.
- Assay selection keys off the local record's VEP consequence and
  name patterns; records with no consequence (e.g. the RYR1 delins)
  fall back to length patterns, and genuinely unusual classes
  (deep intronic, regulatory, structural) are outside the local
  data's scope and would get the generic functional design.
