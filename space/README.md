---
title: Variant Research Agent
emoji: 🧬
colorFrom: green
colorTo: green
sdk: docker
app_port: 7860
license: mit
---

# Variant Research Agent

Variant in, auditable research dossier out — or an honest decline when
the evidence is too thin. The agent plans an investigation, gathers
evidence (frozen ClinVar status, AlphaMissense, REVEL, gene prior,
gnomAD frequency), runs its own small analyses in a no-network sandbox,
judges with a calibrated model, adversarially reviews its own verdict,
and designs the validation experiments that would settle the variant.

The web app is fully hand-built (FastAPI + a custom frontend, no
framework chrome) and adds a data-visualisation layer drawn only from
real data: a predictor heatmap, histograms of the actual local test-set
score distributions with this variant's value marked, a predictor
agreement donut, reviewer severity breakdown, and the published
benchmark results charted from FULL_BENCHMARK_REPORT.md.

This Space runs in **offline mode**: deterministic, local data only,
no LLM, no network gatherers — the same configuration as the published
benchmark (the full temporal test set: all 27,742 variants run end
to end, 92.1% accuracy on concluded cases, 100% decline precision).
**Not for clinical use.**

Source, documentation and full benchmark:
https://github.com/umeshlinga/variant-research-agent

## Data bundled with this Space

The pipeline reads processed tables from the vus-evidence-agent
project, bundled here under `vus_data/`:

- `vus_data/data/processed_v3/test_features.csv`
- `vus_data/data/processed_v2/test_features.csv`
- `vus_data/data/processed_v2/test_predictions_trees.csv`
- `vus_data/data/processed_v3/test_predictions_ensemble.csv`

`server.py` points `VRA_VUS_HOME` at that bundled directory when the
env var is unset. The distribution histograms are computed server-side
from these same tables at runtime.

**Deliberately not bundled:** `data/processed_v2/train_features.csv`
(123 MB). The data loader tolerates its absence — it only removes the
train-set resolution fallback. The full temporal test-set universe of
27,748 variants resolves and researches normally.

Try: `ARSB:c.1178A>C` (a pathogenic-leaning case the built-in reviewer
downgrades from strong to moderate), or `RYR1:c.14761_14762delinsAC`
for an honest decline.
