"""Compute stage (Phase 2): the agent writes and runs its own analyses.

Sits between the gatherers and the judge. For each analysis the stage
prepares an inputs.json from REAL data only (the resolved record, the
gathered evidence, and reference distributions computed from the local
vus-evidence-agent test-set tables — R4), generates a small Python
script, and executes it in the sandbox (see sandbox.py). Scripts that
run cleanly and report real computed content become evidence items
cited as `ANALYSIS:<name>:<script-hash>`; failed, timed-out, or empty
analyses are recorded in the trace and the dossier but NEVER count
toward the decline gate's 3-item bar.

Script provenance: deterministic templates by default (the offline
path always works). When an LLM endpoint is configured AND reachable,
the LLM may propose a script body instead; the proposal must compile
and pass an import/token screen, and it runs in the same sandbox —
any failure falls back to the template. Either way the executed
source is hashed and stored in the trace.

Direction policy: analysis evidence items are Direction.NEUTRAL. The
analyses add independent computed context (percentiles, agreement
statistics), but their directional signal derives from the same
predictors the gatherers already cite — giving them a direction would
double-count those predictors in the judge's fallback sum.
"""
from __future__ import annotations

import re
from typing import Optional

from . import sandbox
from .data import LocalData
from .llm import LLMClient, LLMError
from .model import CalibratedModelAdapter
from .schema import (AnalysisResult, Direction, EvidenceItem,
                     VariantRecord)

# ----------------------------------------------------------------------
# Script templates. Every template honours the sandbox contract:
# read inputs.json, write result.json {summary, results, has_content},
# stdlib only. When a needed datum is absent the script says so and
# reports has_content=False instead of inventing a number (R4).
# ----------------------------------------------------------------------

_POPULATION_CONTEXT = '''\
# Agent analysis: population_context (template-generated)
# Where does this variant's gnomAD allele frequency sit inside the
# distribution of recorded gnomAD frequencies in the local test set?
import json

with open("inputs.json") as f:
    IN = json.load(f)

af = IN.get("af")
ref = IN.get("reference_af") or []


def percentile(dist, x):
    n = len(dist)
    below = sum(1 for v in dist if v < x)
    equal = sum(1 for v in dist if v == x)
    return 100.0 * (below + 0.5 * equal) / n


def ordinal(x):
    # Decimal percentiles always take "th" (62.8th); integer
    # ordinals apply only to whole values (11.0th, 23.0rd).
    if x != int(x):
        return f"{x:.1f}th"
    n = int(x)
    if 10 <= n % 100 <= 20:
        return f"{x:.1f}th"
    return f"{x:.1f}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


if af is None:
    payload = {
        "summary": "No gnomAD allele frequency is available for this "
                   "variant (no recorded or live frequency), so "
                   "population context cannot be computed.",
        "results": {},
        "has_content": False,
    }
elif not ref:
    payload = {
        "summary": "The local reference AF distribution is empty, so "
                   "population context cannot be computed.",
        "results": {},
        "has_content": False,
    }
else:
    srt = sorted(ref)
    n = len(srt)
    med = srt[n // 2] if n % 2 else 0.5 * (srt[n // 2 - 1] + srt[n // 2])
    pct = percentile(ref, af)
    frac_ge = sum(1 for v in ref if v >= af) / n
    if af >= 0.01:
        cls = "common (AF >= 0.01)"
    elif af >= 0.001:
        cls = "low-frequency (0.001 <= AF < 0.01)"
    else:
        cls = "rare (AF < 0.001)"
    results = {
        "allele_frequency": af,
        "af_percentile_in_local_test_set": round(pct, 2),
        "reference_n": n,
        "reference_median_af": med,
        "fraction_of_reference_with_af_ge_variant": round(frac_ge, 4),
        "rarity_class": cls,
    }
    summary = (
        f"gnomAD AF {af:.3g} is at the {ordinal(pct)} percentile of the "
        f"{n} recorded gnomAD frequencies in the local temporal test "
        f"set (median {med:.3g}); rarity class: {cls}.")
    payload = {"summary": summary, "results": results, "has_content": True}

with open("result.json", "w") as f:
    json.dump(payload, f)
print(payload["summary"])
'''

_PREDICTOR_AGREEMENT = '''\
# Agent analysis: predictor_agreement (template-generated)
# Agreement/disagreement statistics across AlphaMissense, REVEL and
# the gene prior — computed from the gathered scores, never asserted.
# Thresholds match the gatherers: REVEL >= 0.644 pathogenic lean,
# <= 0.290 benign lean (Pejaver et al. 2022); AlphaMissense by its
# recorded class; gene prior leans by which side of 0.5 it falls.
import json

with open("inputs.json") as f:
    IN = json.load(f)

leans = {}
if IN.get("am_class") == "likely_pathogenic":
    leans["AlphaMissense"] = 1
elif IN.get("am_class") == "likely_benign":
    leans["AlphaMissense"] = -1
elif IN.get("am_score") is not None:
    leans["AlphaMissense"] = 0
revel = IN.get("revel_score")
if revel is not None:
    leans["REVEL"] = 1 if revel >= 0.644 else -1 if revel <= 0.290 else 0
prior = IN.get("gene_prior")
if prior is not None:
    leans["gene_prior"] = 1 if prior > 0.5 else -1 if prior < 0.5 else 0

names = sorted(leans)
if len(names) < 2:
    payload = {
        "summary": "Predictor agreement needs at least 2 predictors; "
                   f"only {len(names)} available for this variant "
                   f"({', '.join(names) or 'none'}), so no agreement "
                   "statistic is computed.",
        "results": {},
        "has_content": False,
    }
else:
    pairs = agree = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs += 1
            if leans[names[i]] == leans[names[j]]:
                agree += 1
    n_path = sum(1 for v in leans.values() if v == 1)
    n_ben = sum(1 for v in leans.values() if v == -1)
    n_neu = sum(1 for v in leans.values() if v == 0)
    if n_path and not n_ben and not n_neu:
        consensus = "pathogenic (unanimous)"
    elif n_ben and not n_path and not n_neu:
        consensus = "benign (unanimous)"
    elif n_path > n_ben:
        consensus = "pathogenic (majority)"
    elif n_ben > n_path:
        consensus = "benign (majority)"
    elif n_path or n_ben:
        consensus = "split (no majority)"
    else:
        consensus = "neutral (all predictors indeterminate)"
    words = {1: "pathogenic", -1: "benign", 0: "indeterminate"}
    results = {
        "leans": {k: words[v] for k, v in leans.items()},
        "n_predictors": len(names),
        "n_pathogenic_leans": n_path,
        "n_benign_leans": n_ben,
        "n_indeterminate": n_neu,
        "pairs_compared": pairs,
        "pairwise_agreement_fraction": round(agree / pairs, 3),
        "gene_prior_value": prior,
        "consensus": consensus,
    }
    summary = (
        f"Predictor agreement over {len(names)} predictors: "
        f"{n_path} pathogenic lean(s), {n_ben} benign, {n_neu} "
        f"indeterminate; pairwise agreement {agree}/{pairs} pairs; "
        f"consensus: {consensus}.")
    payload = {"summary": summary, "results": results, "has_content": True}

with open("result.json", "w") as f:
    json.dump(payload, f)
print(payload["summary"])
'''

_SCORE_PERCENTILES = '''\
# Agent analysis: score_percentiles (template-generated)
# Local distribution context: where the variant's AlphaMissense and
# REVEL scores sit inside the local test-set score distributions.
import json

with open("inputs.json") as f:
    IN = json.load(f)


def percentile(dist, x):
    n = len(dist)
    below = sum(1 for v in dist if v < x)
    equal = sum(1 for v in dist if v == x)
    return 100.0 * (below + 0.5 * equal) / n


def ordinal(x):
    # Decimal percentiles always take "th" (62.8th); integer
    # ordinals apply only to whole values (11.0th, 23.0rd).
    if x != int(x):
        return f"{x:.1f}th"
    n = int(x)
    if 10 <= n % 100 <= 20:
        return f"{x:.1f}th"
    return f"{x:.1f}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


results = {}
parts = []
for key, label in (("am_score", "AlphaMissense"), ("revel_score", "REVEL")):
    val = IN.get(key)
    dist = (IN.get("reference") or {}).get(key) or []
    if val is None:
        parts.append(f"no {label} score exists for this variant")
        continue
    if not dist:
        parts.append(f"no local {label} reference distribution available")
        continue
    pct = percentile(dist, val)
    results[key] = val
    results[key + "_percentile_in_local_test_set"] = round(pct, 2)
    results[key + "_reference_n"] = len(dist)
    parts.append(
        f"{label} {val:.3f} is at the {ordinal(pct)} percentile of the "
        f"local test-set {label} distribution (n={len(dist)})")

payload = {
    "summary": "; ".join(parts) + ".",
    "results": results,
    "has_content": bool(results),
}

with open("result.json", "w") as f:
    json.dump(payload, f)
print(payload["summary"])
'''

TEMPLATES: dict[str, str] = {
    "population_context": _POPULATION_CONTEXT,
    "predictor_agreement": _PREDICTOR_AGREEMENT,
    "score_percentiles": _SCORE_PERCENTILES,
}

DESCRIPTIONS: dict[str, str] = {
    "population_context": (
        "Percentile of the variant's gnomAD allele frequency within "
        "the distribution of recorded gnomAD frequencies in the local "
        "temporal test set, plus a rarity class."),
    "predictor_agreement": (
        "Agreement statistics across AlphaMissense, REVEL and the "
        "gene prior: per-predictor leans (REVEL thresholds 0.644 / "
        "0.290), pairwise agreement fraction, consensus."),
    "score_percentiles": (
        "Percentiles of the variant's AlphaMissense and REVEL scores "
        "within the local test-set distributions of those scores."),
}

ANALYSIS_ORDER = ["population_context", "predictor_agreement", "score_percentiles"]


# ----------------------------------------------------------------------
# Input preparation — trusted side. Everything here is read from the
# resolved record, the gathered evidence, or the local tables (R4).
# ----------------------------------------------------------------------
_AF_RE = re.compile(r"=\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)")


def _extract_af(evidence: list[EvidenceItem],
                record: VariantRecord) -> Optional[float]:
    """The gnomAD AF for this variant. Preference order: a live
    lookup's value (freshest; parsed from the GNOMAD item's detail,
    whose format the gatherers control), then the record's stored
    frequency at full precision (the recorded item's detail text is
    rounded to 3 significant figures, so the field wins offline),
    then any recorded item's parsed value."""
    for e in evidence:
        if e.live and e.source_id.startswith("GNOMAD:"):
            m = _AF_RE.search(e.detail)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
    if record.gnomad_af_recorded is not None:
        return record.gnomad_af_recorded
    for e in evidence:
        if e.source_id.startswith("GNOMAD:"):
            m = _AF_RE.search(e.detail)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
    return None


def prepare_inputs(name: str, record: VariantRecord,
                   evidence: list[EvidenceItem], data: LocalData,
                   model: CalibratedModelAdapter) -> dict:
    if name == "population_context":
        return {"af": _extract_af(evidence, record),
                "reference_af": data.column_distribution("gnomad_af")}
    if name == "predictor_agreement":
        return {"am_score": record.am_score, "am_class": record.am_class,
                "revel_score": record.revel_score,
                "gene_prior": model.gene_prior(record)}
    if name == "score_percentiles":
        return {"am_score": record.am_score,
                "revel_score": record.revel_score,
                "reference": {
                    "am_score": data.column_distribution("am_score"),
                    "revel_score": data.column_distribution("revel_score"),
                }}
    raise KeyError(name)


# ----------------------------------------------------------------------
# Optional LLM script proposals (R5): allowed only when the endpoint
# answers; the proposal must compile, import nothing beyond
# json/math/statistics, and avoid dangerous tokens. It then runs in
# the same sandbox as templates. Any doubt -> template.
# ----------------------------------------------------------------------
_BANNED_TOKENS = ("socket", "urllib", "requests", "subprocess", "eval(",
                  "exec(", "__import__", "os.system", "popen", "shutil",
                  "pathlib")
_ALLOWED_IMPORTS = {"json", "math", "statistics"}


def _validate_llm_script(source: str) -> bool:
    if any(tok in source for tok in _BANNED_TOKENS):
        return False
    for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                         source, re.M):
        if m.group(1) not in _ALLOWED_IMPORTS:
            return False
    try:
        compile(source, "<llm_analysis>", "exec")
    except SyntaxError:
        return False
    return "inputs.json" in source and "result.json" in source


def _llm_proposal(llm: LLMClient, name: str, inputs: dict) -> Optional[str]:
    keys = ", ".join(sorted(inputs))
    try:
        raw = llm.chat(
            "Write a self-contained Python 3 script for a genetics "
            f"analysis named {name}: {DESCRIPTIONS[name]} "
            "Contract: read inputs.json from the current directory "
            f"(keys: {keys}); use ONLY the standard library modules "
            "json, math, statistics; no network, no file access other "
            "than inputs.json (read) and result.json (write); write "
            "result.json as {\"summary\": str, \"results\": {...}, "
            "\"has_content\": bool}; if a needed input value is null, "
            "report has_content=false and explain in the summary "
            "instead of inventing a number. Output ONLY the Python "
            "code, no commentary, no markdown fences.",
            label=f"compute_{name}", max_tokens=900)
    except LLMError:
        return None
    source = raw.strip()
    if source.startswith("```"):
        source = re.sub(r"^```[A-Za-z]*\n?|\n?```$", "", source).strip()
    return source if _validate_llm_script(source) else None


# ----------------------------------------------------------------------
# Stage entry point
# ----------------------------------------------------------------------
def analysis_to_evidence(result: AnalysisResult) -> Optional[EvidenceItem]:
    """Convert a finished analysis into an evidence item — only when
    it ran cleanly AND carries real computed content. A failed,
    timed-out, or empty analysis returns None: it is recorded in the
    dossier and trace, but never inflates the evidence count."""
    if not result.counts_as_evidence:
        return None
    return EvidenceItem(
        source=f"Agent analysis: {result.name}",
        source_id=f"ANALYSIS:{result.name}:{result.script_sha256[:12]}",
        detail=result.summary,
        direction=Direction.NEUTRAL)


def run_analyses(record: VariantRecord, evidence: list[EvidenceItem],
                 data: LocalData, model: CalibratedModelAdapter,
                 llm: Optional[LLMClient] = None,
                 timeout: float = sandbox.DEFAULT_TIMEOUT,
                 ) -> tuple[list[AnalysisResult], list[EvidenceItem], list[str]]:
    """Run every Phase 2 analysis for this variant.

    Returns (analysis results, new evidence items, event log lines)."""
    results: list[AnalysisResult] = []
    items: list[EvidenceItem] = []
    events: list[str] = []
    use_llm = llm is not None and llm.available()
    for name in ANALYSIS_ORDER:
        inputs = prepare_inputs(name, record, evidence, data, model)
        source, origin = TEMPLATES[name], "template"
        if use_llm:
            proposal = _llm_proposal(llm, name, inputs)
            if proposal is not None:
                source, origin = proposal, "llm"
            else:
                events.append(f"compute: LLM script for {name} rejected "
                              "or unavailable — template used")
        result = sandbox.run_script(name, source, inputs,
                                    timeout=timeout, origin=origin)
        results.append(result)
        events.append(
            f"compute: {name} [{origin}] status={result.status} "
            f"({result.duration_s:.2f}s, sha {result.script_sha256[:12]})"
            + (f" — {result.error}" if result.error else ""))
        item = analysis_to_evidence(result)
        if item is not None:
            items.append(item)
    return results, items, events
