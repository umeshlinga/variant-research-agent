#!/usr/bin/env python3
"""Phase 4 benchmark: the full Variant Research Agent pipeline over a
stratified sample of the vus-evidence-agent temporal test set.

TEMPORAL-INTEGRITY DESIGN (R1) — read this before the code:

  * The pipeline's own data layer (variant_research_agent.data) reads
    ONLY prediction-time columns. sig_now / label are structurally
    whitelisted out of every table the pipeline can touch.
  * This harness reads sig_now / label itself, from the v3 test
    features table, for exactly two evaluation-side purposes:
      (1) to STRATIFY the sample (so every cell of the frame is
          represented), and
      (2) to SCORE the finished dossiers (the temporal truth: what
          ClinVar says NOW about a variant that was uncertain at the
          2024-01 freeze).
    Truth is never passed to the pipeline: each run receives only the
    query string "allele:<id>". Scoring reads the truth after the
    dossier files are written.

MODE: deterministic offline (VRA_OFFLINE=1 forced below, live=False).
Live gnomAD / PubMed calls are OFF, so the run is reproducible from
the recorded local data alone. Differences vs live mode: the gnomAD
item comes from the recorded lookup (same values the source project
harvested), and PubMed literature items never appear offline, so the
evidence counts (and therefore some gate outcomes) are conservative
relative to a live run.

SAMPLING FRAME (honest): the temporal test set is BY CONSTRUCTION the
set of variants that were uncertain at the freeze and have since been
reclassified — see vus-evidence-agent SPLIT_REPORT.md. Every one of
its 27,748 rows therefore has a resolved eventual label; the
"still-uncertain" truth stratum has ZERO members in this data and no
sample can be drawn from it. The frame below reports that cell's size
as 0 rather than pretending otherwise. Strata actually sampled:
(recorded GBM+R probability available vs not) x (eventual truth
pathogenic-leaning vs benign-leaning), proportional allocation,
fixed seed.

Usage:
  .venv/bin/python scripts/benchmark.py [--n 300] [--seed 20261030]
                                        [--out benchmark]
Outputs (under --out):
  sample.json     the frame (cell sizes) + the sampled allele ids
  results.jsonl   one record per sampled variant, appended as runs finish
  dossiers/       the dossiers + JSON traces the pipeline wrote
  summary.json    aggregate metrics (also printed at the end)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

# Deterministic offline mode, forced BEFORE the pipeline is imported
# (the LLM layer's offline switch is an environment variable).
os.environ["VRA_OFFLINE"] = "1"

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "src"))

DEFAULT_SEED = 20261030
DEFAULT_N = 300

TRUTH_PATHOGENIC = "pathogenic"
TRUTH_BENIGN = "benign"
TRUTH_UNCERTAIN = "uncertain"


# ----------------------------------------------------------------------
# Evaluation-side truth (never enters the pipeline)
# ----------------------------------------------------------------------
def truth_lean(sig_now: str | None, label: str | None) -> str:
    """Map the post-cutoff ClinVar status to the temporal-truth lean.

    A variant whose current status is still uncertain / conflicting /
    not provided is 'uncertain' regardless of any label column; the
    source project's split defines label 1 = pathogenic-side
    (P / LP / P-LP) and 0 = benign-side (B / LB / B-LB) for resolved
    variants."""
    s = (sig_now or "").strip().lower()
    if (not s or "uncertain" in s or "conflicting" in s
            or s == "not provided"):
        return TRUTH_UNCERTAIN
    if label == "1":
        return TRUTH_PATHOGENIC
    if label == "0":
        return TRUTH_BENIGN
    if "pathogenic" in s:
        return TRUTH_PATHOGENIC
    if "benign" in s:
        return TRUTH_BENIGN
    return TRUTH_UNCERTAIN


def load_truth(vus_home: Path) -> dict[int, dict]:
    """EVALUATION-SIDE ONLY: allele_id -> {sig_now, label, truth}.

    This deliberately bypasses variant_research_agent.data (whose
    column whitelist exists precisely so the pipeline can never see
    these fields) and reads the two evaluation columns directly."""
    path = vus_home / "data/processed_v3/test_features.csv"
    out: dict[int, dict] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            aid = int(row["allele_id"])
            out[aid] = {
                "sig_now": row.get("sig_now", ""),
                "label": row.get("label", ""),
                "truth": truth_lean(row.get("sig_now"), row.get("label")),
            }
    return out


# ----------------------------------------------------------------------
# Sampling frame
# ----------------------------------------------------------------------
def build_frame(truth: dict[int, dict], prob_ids: set[int]) -> dict:
    """Cell key (prob_available, truth_lean) -> sorted allele id list."""
    frame: dict[tuple[bool, str], list[int]] = {}
    for aid, t in truth.items():
        key = (aid in prob_ids, t["truth"])
        frame.setdefault(key, []).append(aid)
    for ids in frame.values():
        ids.sort()
    return frame


def largest_remainder_allocation(counts: dict, total: int) -> dict:
    """Split `total` across cells proportionally to their sizes.
    Empty cells get 0; no cell gets more than its size."""
    sizes = {k: len(v) for k, v in counts.items()}
    pool = sum(sizes.values())
    if pool == 0 or total <= 0:
        return {k: 0 for k in sizes}
    total = min(total, pool)
    raw = {k: total * s / pool for k, s in sizes.items()}
    alloc = {k: min(int(raw[k]), sizes[k]) for k in sizes}
    remaining = total - sum(alloc.values())
    by_remainder = sorted(sizes, key=lambda k: (-(raw[k] - int(raw[k])), str(k)))
    for k in by_remainder:
        if remaining <= 0:
            break
        add = min(remaining, sizes[k] - alloc[k])
        alloc[k] += add
        remaining -= add
    return alloc


def sample_frame(frame: dict, total: int, seed: int) -> dict:
    """Deterministic stratified sample: {cell_key: [allele_id, ...]}."""
    alloc = largest_remainder_allocation(frame, total)
    rng = random.Random(seed)
    sample: dict[tuple[bool, str], list[int]] = {}
    for key in sorted(frame, key=str):
        ids = list(frame[key])
        rng.shuffle(ids)
        sample[key] = sorted(ids[:alloc[key]])
    return sample


# ----------------------------------------------------------------------
# Metrics (pure functions — unit-tested on synthetic inputs)
# ----------------------------------------------------------------------
def brier_score(probs: list[float], labels: list[int]) -> float:
    if not probs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def expected_calibration_error(probs: list[float], labels: list[int],
                               n_bins: int = 10) -> float:
    """Equal-width-bin ECE over [0, 1], count-weighted |conf - acc|."""
    if not probs:
        return float("nan")
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, labels):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    ece = 0.0
    for b in bins:
        if not b:
            continue
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(y for _, y in b) / len(b)
        ece += (len(b) / len(probs)) * abs(conf - acc)
    return ece


def decline_precision(records: list[dict]) -> dict:
    """Of the DECLINED cases, how many declines were protective: the
    underlying (pre-gate) judgment was indeterminate, or leaned the
    wrong way vs the temporal truth, or the truth itself is still
    uncertain (so no conclusion could have been right). The complement
    is the over-caution count: declined although the underlying lean
    already matched the truth."""
    declined = [r for r in records if r["resolved"] and not r["concluded"]]
    protective = overcautious = 0
    for r in declined:
        if r["truth"] == TRUTH_UNCERTAIN or r["judgment_lean"] == "indeterminate" \
                or r["judgment_lean"] != r["truth"]:
            protective += 1
        else:
            overcautious += 1
    return {
        "declined": len(declined),
        "protective": protective,
        "overcautious": overcautious,
        "precision": (protective / len(declined)) if declined else float("nan"),
    }


def summarise(records: list[dict]) -> dict:
    """All headline metrics, computed only from runs that happened."""
    resolved = [r for r in records if r["resolved"]]
    concluded = [r for r in resolved if r["concluded"]]
    scorable = [r for r in concluded if r["truth"] in
                (TRUTH_PATHOGENIC, TRUTH_BENIGN)]
    correct = [r for r in scorable if r["judgment_lean"] == r["truth"]]

    cal = [r for r in scorable
           if r["model_prob_pathogenic"] is not None]
    cal_probs = [r["model_prob_pathogenic"] for r in cal]
    cal_labels = [1 if r["truth"] == TRUTH_PATHOGENIC else 0 for r in cal]

    all_prob = [r for r in resolved
                if r["model_prob_pathogenic"] is not None
                and r["truth"] in (TRUTH_PATHOGENIC, TRUTH_BENIGN)]

    down = [r for r in scorable if r["downgraded"]]
    nodown = [r for r in scorable if not r["downgraded"]]

    def acc(rs: list[dict]) -> float:
        if not rs:
            return float("nan")
        return sum(1 for r in rs if r["judgment_lean"] == r["truth"]) / len(rs)

    verdicts: dict[str, int] = {}
    for r in resolved:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    analyses_clean = sum(1 for r in resolved
                         if r["analyses_failed"] == 0
                         and r["analyses_timeout"] == 0)

    return {
        "sampled": len(records),
        "resolved": len(resolved),
        "unresolved": len(records) - len(resolved),
        "coverage": (len(resolved) / len(records)) if records else float("nan"),
        "verdict_distribution": verdicts,
        "concluded": len(concluded),
        "declined": len(resolved) - len(concluded),
        "decline_rate": ((len(resolved) - len(concluded)) / len(resolved)
                         if resolved else float("nan")),
        "accuracy_concluded": acc(scorable),
        "accuracy_concluded_n": len(scorable),
        "accuracy_concluded_correct": len(correct),
        "calibration_concluded": {
            "n": len(cal),
            "ece": expected_calibration_error(cal_probs, cal_labels),
            "brier": brier_score(cal_probs, cal_labels),
        },
        "calibration_all_scored": {
            "n": len(all_prob),
            "ece": expected_calibration_error(
                [r["model_prob_pathogenic"] for r in all_prob],
                [1 if r["truth"] == TRUTH_PATHOGENIC else 0 for r in all_prob]),
            "brier": brier_score(
                [r["model_prob_pathogenic"] for r in all_prob],
                [1 if r["truth"] == TRUTH_PATHOGENIC else 0 for r in all_prob]),
        },
        "decline": decline_precision(records),
        "reviewer": {
            "downgraded_concluded": len(down),
            "downgrade_rate_concluded": (len(down) / len(scorable)
                                         if scorable else float("nan")),
            "accuracy_downgraded": acc(down),
            "accuracy_downgraded_n": len(down),
            "accuracy_not_downgraded": acc(nodown),
            "accuracy_not_downgraded_n": len(nodown),
        },
        "analyses_execution": {
            "runs_with_all_analyses_clean": analyses_clean,
            "fraction_clean": (analyses_clean / len(resolved)
                               if resolved else float("nan")),
        },
    }


def pick_failure_examples(records: list[dict], k: int = 3) -> list[dict]:
    """Concluded-but-wrong cases, most confident errors first."""
    wrong = [r for r in records
             if r["resolved"] and r["concluded"]
             and r["truth"] in (TRUTH_PATHOGENIC, TRUTH_BENIGN)
             and r["judgment_lean"] != r["truth"]]

    def confidence_of_error(r: dict) -> float:
        p = r["model_prob_pathogenic"]
        if p is not None:
            return abs(p - (1.0 if r["truth"] == TRUTH_PATHOGENIC else 0.0))
        return 0.5  # uncalibrated errors rank below confident model errors

    wrong.sort(key=confidence_of_error, reverse=True)
    return wrong[:k]


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------
def run_benchmark(n: int = DEFAULT_N, seed: int = DEFAULT_SEED,
                  out_dir: Path | None = None) -> dict:
    from variant_research_agent.data import LocalData, vus_home
    from variant_research_agent.graph import _Ctx, build_graph
    from variant_research_agent.llm import LLMClient

    out_dir = out_dir or (_PROJECT / "benchmark")
    dossiers_dir = out_dir / "dossiers"
    out_dir.mkdir(parents=True, exist_ok=True)

    home = vus_home()
    truth = load_truth(home)
    data = LocalData()
    prob_ids = set(data.gbm_predictions().keys())
    frame = build_frame(truth, prob_ids)
    sample = sample_frame(frame, n, seed)

    frame_report = {
        "seed": seed,
        "requested_n": n,
        "frame_universe": len(truth),
        "cells": {
            f"prob={'yes' if k[0] else 'no'}|truth={k[1]}": {
                "frame_size": len(frame[k]),
                "sampled": len(sample[k]),
            }
            for k in sorted(frame, key=str)
        },
        "note": ("The still-uncertain truth stratum is empty in the "
                 "temporal test set BY CONSTRUCTION (the set contains "
                 "only variants reclassified after the 2024-01 freeze), "
                 "so no sample could be drawn from it."),
        "sample_allele_ids": {f"prob={'yes' if k[0] else 'no'}|truth={k[1]}":
                              sample[k] for k in sorted(frame, key=str)},
    }
    (out_dir / "sample.json").write_text(json.dumps(frame_report, indent=2))

    ctx = _Ctx(data, LLMClient())  # LLMClient is offline: VRA_OFFLINE=1
    graph = build_graph(ctx)

    flat = [aid for key in sorted(sample, key=str) for aid in sample[key]]
    stratum_of = {aid: key for key in sorted(sample, key=str)
                  for aid in sample[key]}
    print(f"benchmark: frame={len(truth)} sampled={len(flat)} "
          f"seed={seed} mode=offline", flush=True)

    records: list[dict] = []
    results_path = out_dir / "results.jsonl"
    t0 = time.time()
    with open(results_path, "w") as jf:
        for i, aid in enumerate(flat, 1):
            t = truth[aid]
            prob_avail, _ = stratum_of[aid]
            rec: dict = {
                "allele_id": aid,
                "prob_available": prob_avail,
                "sig_now": t["sig_now"],
                "truth": t["truth"],
                "resolved": False,
                "error": None,
            }
            try:
                state = graph.invoke({
                    "query": f"allele:{aid}", "live": False,
                    "out_dir": str(dossiers_dir), "events": [], "notes": []})
            except Exception as e:  # resolution or pipeline failure
                rec["error"] = f"{type(e).__name__}: {e}"
                records.append(rec)
                jf.write(json.dumps(rec) + "\n")
                jf.flush()
                continue
            j = state["judgment"]
            gate = state["gate"]
            review = state.get("review") or {}
            analyses = state.get("analyses") or []
            rec.update({
                "resolved": True,
                "gene": state["record"]["gene"],
                "name": state["record"]["name"],
                "concluded": bool(gate["passed"]),
                "verdict": ("concluded_" + j["lean"] if gate["passed"]
                            else "declined"),
                "judgment_lean": j["lean"],
                "basis": j["basis"],
                "strength_final": j["strength"],
                "model_prob_pathogenic": j["model_prob_pathogenic"],
                "evidence_score": j["evidence_score"],
                "evidence_count": gate["evidence_count"],
                "downgraded": bool(review.get("downgraded")),
                "strength_before": review.get("strength_before") or "",
                "n_critiques": len(review.get("critiques", [])),
                "n_material": sum(1 for c in review.get("critiques", [])
                                  if c["severity"] == "material"),
                "material_checks": [c["check"] for c in
                                    review.get("critiques", [])
                                    if c["severity"] == "material"],
                "critiques": review.get("critiques", []),
                "evidence": [{"source": e["source"],
                              "source_id": e["source_id"],
                              "detail": e["detail"],
                              "direction": e["direction"]}
                             for e in state["evidence"]],
                "analyses_failed": sum(1 for a in analyses
                                       if a["status"] == "failed"),
                "analyses_timeout": sum(1 for a in analyses
                                        if a["status"] == "timeout"),
                "dossier": state["outputs"]["dossier"],
                "duration_s": None,
            })
            records.append(rec)
            jf.write(json.dumps(rec) + "\n")
            jf.flush()
            if i % 25 == 0 or i == len(flat):
                el = time.time() - t0
                print(f"  {i}/{len(flat)} runs, {el:.0f}s elapsed, "
                      f"{el / i:.2f}s/run", flush=True)

    metrics = summarise(records)
    failures = pick_failure_examples(records)
    summary = {
        "seed": seed,
        "mode": "offline (VRA_OFFLINE=1, live gatherers off)",
        "frame": frame_report,
        "metrics": metrics,
        "failure_examples": [
            {k: f[k] for k in ("allele_id", "gene", "name", "truth",
                               "sig_now", "judgment_lean", "basis",
                               "strength_final", "model_prob_pathogenic",
                               "evidence_score", "evidence_count",
                               "downgraded", "strength_before",
                               "material_checks", "critiques", "evidence",
                               "dossier")}
            for f in failures
        ],
        "wall_time_s": time.time() - t0,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _fmt(x: float) -> str:
    if isinstance(x, float) and x != x:  # NaN
        return "n/a"
    return f"{x:.4f}" if isinstance(x, float) else str(x)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark",
                                 description="Phase 4 temporal benchmark.")
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=str(_PROJECT / "benchmark"))
    args = ap.parse_args(argv)
    summary = run_benchmark(args.n, args.seed, Path(args.out))
    m = summary["metrics"]
    print("\n=== BENCHMARK SUMMARY ===")
    print(f"sampled={m['sampled']} resolved={m['resolved']} "
          f"coverage={_fmt(m['coverage'])}")
    print(f"verdicts={m['verdict_distribution']}")
    print(f"accuracy on concluded = {_fmt(m['accuracy_concluded'])} "
          f"(n={m['accuracy_concluded_n']})")
    cal = m["calibration_concluded"]
    print(f"calibration on concluded scored subset: n={cal['n']} "
          f"ECE={_fmt(cal['ece'])} Brier={_fmt(cal['brier'])}")
    d = m["decline"]
    print(f"decline rate={_fmt(m['decline_rate'])} "
          f"decline precision={_fmt(d['precision'])} "
          f"(protective={d['protective']}, overcautious={d['overcautious']})")
    r = m["reviewer"]
    print(f"downgrade rate (concluded)={_fmt(r['downgrade_rate_concluded'])}; "
          f"accuracy downgraded={_fmt(r['accuracy_downgraded'])} "
          f"(n={r['accuracy_downgraded_n']}) vs not="
          f"{_fmt(r['accuracy_not_downgraded'])} "
          f"(n={r['accuracy_not_downgraded_n']})")
    print(f"wall time {summary['wall_time_s']:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
