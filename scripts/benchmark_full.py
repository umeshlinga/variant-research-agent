#!/usr/bin/env python3
"""Full-set benchmark: the Variant Research Agent pipeline over EVERY
unique variant of the vus-evidence-agent ClinVar temporal test set.

This is the population version of scripts/benchmark.py (which ran a
300-variant stratified sample). Same pipeline path, same deterministic
offline mode (VRA_OFFLINE=1, live=False), same record schema, plus
per-status analysis counts.

TEMPORAL INTEGRITY (R1) — identical design to the sample harness:
  * The pipeline's data layer never reads sig_now / label (structural
    whitelist in variant_research_agent.data).
  * This runner reads truth (sig_now / label) evaluation-side only,
    via scripts.benchmark.load_truth, writes it into the result
    records for post-hoc scoring, and passes ONLY the string
    "allele:<id>" to the pipeline.

CHECKPOINT / RESUME:
  * Results stream to <out>/results.jsonl, one JSON record per variant,
    appended and flushed as each run completes.
  * On startup, allele ids already present in results.jsonl are
    skipped, so an interrupted run resumes where it stopped and loses
    at most the in-flight chunk.

PARALLELISM:
  * multiprocessing.Pool; each worker builds its own LocalData + graph
    once (initializer) and reuses it for every task.
  * Worker count: --workers (default: cpu_count, measured on the bench
    VM below); the parent process only streams results to disk.

Usage:
  .venv/bin/python scripts/benchmark_full.py [--workers N]
                                             [--out benchmark/fullset]
                                             [--limit N]   (smoke tests)
Outputs (under --out):
  results.jsonl   one record per variant (the checkpoint)
  dossiers/       dossiers + JSON traces written by the pipeline
  summary.json    aggregate metrics (benchmark.summarise + extensions)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ["VRA_OFFLINE"] = "1"

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "src"))
sys.path.insert(0, str(_PROJECT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "sample_benchmark", _PROJECT / "scripts" / "benchmark.py")
_bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bm)

# ----------------------------------------------------------------------
# Worker side (one LocalData + graph per process)
# ----------------------------------------------------------------------
_G: dict = {}


def _worker_init(dossiers_dir: str) -> None:
    from variant_research_agent.data import LocalData
    from variant_research_agent.graph import _Ctx, build_graph
    from variant_research_agent.llm import LLMClient

    _G["graph"] = build_graph(_Ctx(LocalData(), LLMClient()))
    _G["dossiers_dir"] = dossiers_dir


def _worker_run(task: tuple[int, bool, str, str]) -> dict:
    aid, prob_avail, sig_now, truth = task
    rec: dict = {
        "allele_id": aid,
        "prob_available": prob_avail,
        "sig_now": sig_now,
        "truth": truth,
        "resolved": False,
        "error": None,
    }
    t0 = time.time()
    try:
        state = _G["graph"].invoke({
            "query": f"allele:{aid}", "live": False,
            "out_dir": _G["dossiers_dir"], "events": [], "notes": []})
    except Exception as e:  # resolution or pipeline failure
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["duration_s"] = round(time.time() - t0, 3)
        return rec
    j = state["judgment"]
    gate = state["gate"]
    review = state.get("review") or {}
    analyses = state.get("analyses") or []
    status_counts: dict[str, int] = {}
    for a in analyses:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    rec.update({
        "resolved": True,
        "gene": state["record"]["gene"],
        "name": state["record"]["name"],
        "concluded": bool(gate["passed"]),
        "verdict": ("concluded_" + j["lean"] if gate["passed"] else "declined"),
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
        "material_checks": [c["check"] for c in review.get("critiques", [])
                            if c["severity"] == "material"],
        "critiques": review.get("critiques", []),
        "evidence": [{"source": e["source"], "source_id": e["source_id"],
                      "detail": e["detail"], "direction": e["direction"]}
                     for e in state["evidence"]],
        "n_analyses": len(analyses),
        "analyses_status_counts": status_counts,
        "analyses_failed": status_counts.get("failed", 0),
        "analyses_timeout": status_counts.get("timeout", 0),
        "dossier": state["outputs"]["dossier"],
        "duration_s": round(time.time() - t0, 3),
    })
    return rec


# ----------------------------------------------------------------------
# Checkpoint handling
# ----------------------------------------------------------------------
def load_checkpoint(results_path: Path) -> dict[int, dict]:
    done: dict[int, dict] = {}
    if not results_path.exists():
        return done
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn tail line from an interrupted write
            if not rec.get("resolved"):
                continue  # errored runs are retried, never checkpointed
            done[int(rec["allele_id"])] = rec
    return done


# ----------------------------------------------------------------------
# Extended metrics (beyond benchmark.summarise)
# ----------------------------------------------------------------------
def auroc(probs: list[float], labels: list[int]) -> float:
    """Mann-Whitney AUROC with average ranks for ties."""
    n = len(probs)
    if n == 0:
        return float("nan")
    order = sorted(range(n), key=lambda i: probs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and probs[order[j + 1]] == probs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    n_pos = sum(labels)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    rank_sum_pos = sum(r for r, y in zip(ranks, labels) if y == 1)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def extended_metrics(records: list[dict]) -> dict:
    resolved = [r for r in records if r["resolved"]]
    concluded = [r for r in resolved if r["concluded"]]
    scorable = [r for r in concluded
                if r["truth"] in (_bm.TRUTH_PATHOGENIC, _bm.TRUTH_BENIGN)]

    def acc(rs: list[dict]) -> float:
        return (sum(1 for r in rs if r["judgment_lean"] == r["truth"]) / len(rs)
                if rs else float("nan"))

    by_truth = {}
    for t in (_bm.TRUTH_PATHOGENIC, _bm.TRUTH_BENIGN):
        sub = [r for r in scorable if r["truth"] == t]
        by_truth[t] = {"n": len(sub), "accuracy": acc(sub),
                       "correct": sum(1 for r in sub
                                      if r["judgment_lean"] == r["truth"])}
    cal = [r for r in scorable if r["model_prob_pathogenic"] is not None]
    probs = [r["model_prob_pathogenic"] for r in cal]
    labels = [1 if r["truth"] == _bm.TRUTH_PATHOGENIC else 0 for r in cal]

    correct = [r for r in scorable if r["judgment_lean"] == r["truth"]]
    wrong = [r for r in scorable if r["judgment_lean"] != r["truth"]]
    status_totals: dict[str, int] = {}
    for r in resolved:
        for k, v in (r.get("analyses_status_counts") or {}).items():
            status_totals[k] = status_totals.get(k, 0) + v
    return {
        "accuracy_by_truth": by_truth,
        "auroc_concluded": auroc(probs, labels),
        "auroc_concluded_n": len(cal),
        "reviewer_extended": {
            "material_rate_concluded": (
                sum(1 for r in scorable if r["n_material"] > 0) / len(scorable)
                if scorable else float("nan")),
            "concluded_with_material": sum(1 for r in scorable
                                           if r["n_material"] > 0),
            "downgrade_rate_correct": (
                sum(1 for r in correct if r["downgraded"]) / len(correct)
                if correct else float("nan")),
            "downgrade_rate_wrong": (
                sum(1 for r in wrong if r["downgraded"]) / len(wrong)
                if wrong else float("nan")),
            "downgraded_correct_n": sum(1 for r in correct if r["downgraded"]),
            "correct_n": len(correct),
            "downgraded_wrong_n": sum(1 for r in wrong if r["downgraded"]),
            "wrong_n": len(wrong),
        },
        "analyses_status_totals": status_totals,
        "analyses_total": sum(status_totals.values()),
    }


def full_summary(records: list[dict]) -> dict:
    base = _bm.summarise(records)
    ext = extended_metrics(records)
    base.update(ext)
    return base


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark_full")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", default=str(_PROJECT / "benchmark" / "fullset"))
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke tests only: cap the universe size")
    args = ap.parse_args(argv)

    from multiprocessing import Pool

    from variant_research_agent.data import LocalData, vus_home

    out_dir = Path(args.out)
    dossiers_dir = out_dir / "dossiers"
    out_dir.mkdir(parents=True, exist_ok=True)
    dossiers_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    home = vus_home()
    truth = load_truth = _bm.load_truth(home)
    prob_ids = set(LocalData().gbm_predictions().keys())
    universe = sorted(truth.keys())
    if args.limit:
        universe = universe[:args.limit]

    done = load_checkpoint(results_path)
    todo = [aid for aid in universe if aid not in done]
    print(f"full benchmark: universe={len(universe)} already_done={len(done)} "
          f"todo={len(todo)} workers={args.workers} mode=offline", flush=True)
    if not todo:
        records = [done[a] for a in universe]
        summary = {"metrics": full_summary(records),
                   "failure_examples": _bm.pick_failure_examples(records, k=10),
                   "wall_time_s": 0.0}
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        print("nothing to do; summary rewritten from checkpoint", flush=True)
        return 0

    tasks = [(aid, aid in prob_ids, truth[aid]["sig_now"], truth[aid]["truth"])
             for aid in todo]
    t0 = time.time()
    n_done = 0
    n_env_blocked = 0
    rate_checked = len(done) >= 500
    with open(results_path, "a") as jf, Pool(
            processes=args.workers, initializer=_worker_init,
            initargs=(str(dossiers_dir),)) as pool:
        for rec in pool.imap_unordered(_worker_run, tasks, chunksize=20):
            if (not rec["resolved"] and rec.get("error", "")
                    .startswith("PermissionError")):
                # Environmental restriction (observed 2026-10-30: a
                # detached session lost subprocess permission mid-run
                # and every subsequent run failed EPERM). Do NOT
                # checkpoint these — a later resume retries them. If
                # the block is total, bail out early instead of
                # burning the whole pass.
                n_env_blocked += 1
                if n_env_blocked >= 50 and n_done == 0:
                    print("ENV_BLOCKED: 50 consecutive PermissionError "
                          "results and no successful run this session; "
                          "aborting so a later resume can retry.",
                          flush=True)
                    pool.terminate()
                    return 3
                continue
            jf.write(json.dumps(rec) + "\n")
            jf.flush()
            done[int(rec["allele_id"])] = rec
            n_done += 1
            total_done = len(done)
            if not rate_checked and total_done >= 500:
                rate_checked = True
                el = time.time() - t0
                rate = n_done / el
                remaining = (len(universe) - total_done) / rate
                print(f"RATE_CHECK first500: {n_done} new runs in {el:.0f}s "
                      f"this session ({rate:.2f} runs/s, "
                      f"{1 / rate:.3f} s/run); projected remaining "
                      f"{remaining / 60:.0f} min; projected total for full "
                      f"universe at this rate "
                      f"{len(universe) / rate / 60:.0f} min", flush=True)
            if n_done % 250 == 0:
                el = time.time() - t0
                rate = n_done / el
                eta = (len(todo) - n_done) / rate if rate else 0
                print(f"  progress {total_done}/{len(universe)} "
                      f"({n_done} this session), {el:.0f}s elapsed, "
                      f"{1 / rate:.3f} s/run, ETA {eta / 60:.0f} min",
                      flush=True)
            if n_done % 1000 == 0:
                os.fsync(jf.fileno())

    wall = time.time() - t0
    records = [done[a] for a in universe]
    failures = _bm.pick_failure_examples(records, k=10)
    summary = {
        "mode": "offline (VRA_OFFLINE=1, live gatherers off)",
        "universe": len(universe),
        "workers": args.workers,
        "metrics": full_summary(records),
        "failure_examples": [
            {k: f.get(k) for k in ("allele_id", "gene", "name", "truth",
                                   "sig_now", "judgment_lean", "basis",
                                   "strength_final", "model_prob_pathogenic",
                                   "evidence_score", "evidence_count",
                                   "downgraded", "strength_before",
                                   "material_checks", "critiques", "evidence",
                                   "dossier")}
            for f in failures],
        "wall_time_s": wall,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    m = summary["metrics"]
    print(f"\n=== FULL BENCHMARK DONE === wall {wall / 60:.1f} min")
    print(f"resolved={m['resolved']}/{len(universe)} "
          f"concluded={m['concluded']} declined={m['declined']} "
          f"decline_rate={m['decline_rate']:.4f}")
    print(f"accuracy_concluded={m['accuracy_concluded']:.4f} "
          f"(n={m['accuracy_concluded_n']}) "
          f"auroc={m['auroc_concluded']:.4f} (n={m['auroc_concluded_n']})")
    cal = m["calibration_concluded"]
    print(f"calibration concluded: n={cal['n']} ECE={cal['ece']:.4f} "
          f"Brier={cal['brier']:.4f}")
    d = m["decline"]
    print(f"decline precision={d['precision']:.4f} "
          f"(protective={d['protective']}, overcautious={d['overcautious']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
