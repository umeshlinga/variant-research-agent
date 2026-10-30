"""Unit tests for the Phase 4 benchmark's pure metric functions.

The benchmark harness lives in scripts/benchmark.py (not a package),
so it is loaded by path. These tests use SYNTHETIC inputs only: the
point is that every metric the report quotes is a tested function of
whatever runs actually happened — the harness never hardcodes a
number (R4).
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"
_spec = importlib.util.spec_from_file_location("vra_benchmark", _SCRIPT)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


# ----------------------------------------------------------------------
# truth mapping
# ----------------------------------------------------------------------
def test_truth_lean_mapping():
    assert bench.truth_lean("Pathogenic", "1") == "pathogenic"
    assert bench.truth_lean("Likely pathogenic", "1") == "pathogenic"
    assert bench.truth_lean("Benign/Likely benign", "0") == "benign"
    assert bench.truth_lean("Likely benign", "0") == "benign"
    assert bench.truth_lean("Uncertain significance", "") == "uncertain"
    assert bench.truth_lean(
        "Conflicting interpretations of pathogenicity", "") == "uncertain"
    assert bench.truth_lean("not provided", "") == "uncertain"
    assert bench.truth_lean("", "") == "uncertain"


# ----------------------------------------------------------------------
# calibration metrics
# ----------------------------------------------------------------------
def test_brier_known_values():
    assert bench.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert bench.brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)
    assert math.isnan(bench.brier_score([], []))


def test_ece_perfect_and_known_case():
    # perfectly calibrated constructed case: 10 predictions at 0.2
    # with exactly 2 positives, 10 at 0.8 with exactly 8 positives.
    probs = [0.2] * 10 + [0.8] * 10
    labels = [1, 1] + [0] * 8 + [1] * 8 + [0] * 2
    assert bench.expected_calibration_error(probs, labels) == pytest.approx(0.0)
    # all confidence 0.9, half positive: one bin, |0.9 - 0.5| = 0.4
    assert bench.expected_calibration_error(
        [0.9] * 10, [1] * 5 + [0] * 5) == pytest.approx(0.4)
    assert math.isnan(bench.expected_calibration_error([], []))


# ----------------------------------------------------------------------
# allocation + sampling
# ----------------------------------------------------------------------
def test_allocation_proportional_and_bounded():
    frame = {("a",): list(range(100)), ("b",): list(range(300)),
             ("c",): []}
    alloc = bench.largest_remainder_allocation(frame, 40)
    assert sum(alloc.values()) == 40
    assert alloc[("c",)] == 0                    # empty cell stays empty
    assert alloc[("a",)] == pytest.approx(10, abs=1)
    assert alloc[("b",)] == pytest.approx(30, abs=1)
    # never allocate more than the cell holds
    alloc = bench.largest_remainder_allocation(frame, 10_000)
    assert alloc[("a",)] == 100 and alloc[("b",)] == 300


def test_sampling_is_deterministic_and_within_frame():
    frame = {(True, "pathogenic"): list(range(50)),
             (False, "benign"): list(range(100, 160))}
    s1 = bench.sample_frame(frame, 30, seed=7)
    s2 = bench.sample_frame(frame, 30, seed=7)
    assert s1 == s2
    assert sum(len(v) for v in s1.values()) == 30
    for key, ids in s1.items():
        assert set(ids) <= set(frame[key])


# ----------------------------------------------------------------------
# decline precision
# ----------------------------------------------------------------------
def _rec(**kw):
    base = {"resolved": True, "concluded": False, "judgment_lean": "benign",
            "truth": "benign", "model_prob_pathogenic": None,
            "downgraded": False, "verdict": "declined",
            "analyses_failed": 0, "analyses_timeout": 0}
    base.update(kw)
    return base


def test_decline_precision_counts():
    records = [
        _rec(judgment_lean="pathogenic", truth="benign"),   # wrong-way: protective
        _rec(judgment_lean="indeterminate", truth="pathogenic"),  # protective
        _rec(judgment_lean="benign", truth="benign"),       # over-cautious
        _rec(judgment_lean="pathogenic", truth="uncertain"),  # protective
    ]
    out = bench.decline_precision(records)
    assert out["declined"] == 4
    assert out["protective"] == 3
    assert out["overcautious"] == 1
    assert out["precision"] == pytest.approx(0.75)


# ----------------------------------------------------------------------
# summarise on a fabricated run set with hand-computed expectations
# ----------------------------------------------------------------------
def test_summarise_hand_computed():
    records = [
        # concluded, model-scored, correct, not downgraded
        _rec(concluded=True, verdict="concluded_pathogenic",
             judgment_lean="pathogenic", truth="pathogenic",
             model_prob_pathogenic=0.9),
        # concluded, model-scored, WRONG, downgraded
        _rec(concluded=True, verdict="concluded_pathogenic",
             judgment_lean="pathogenic", truth="benign",
             model_prob_pathogenic=0.8, downgraded=True),
        # concluded, evidence-scored, correct
        _rec(concluded=True, verdict="concluded_benign",
             judgment_lean="benign", truth="benign"),
        # declined, protective
        _rec(judgment_lean="indeterminate", truth="pathogenic"),
        # unresolved
        _rec(resolved=False, verdict="", judgment_lean="",
             truth="benign"),
    ]
    m = bench.summarise(records)
    assert m["sampled"] == 5 and m["resolved"] == 4 and m["unresolved"] == 1
    assert m["coverage"] == pytest.approx(0.8)
    assert m["concluded"] == 3 and m["declined"] == 1
    assert m["verdict_distribution"] == {
        "concluded_pathogenic": 2, "concluded_benign": 1, "declined": 1}
    assert m["accuracy_concluded"] == pytest.approx(2 / 3)
    cal = m["calibration_concluded"]
    assert cal["n"] == 2
    assert cal["brier"] == pytest.approx(((0.9 - 1) ** 2 + (0.8 - 0) ** 2) / 2)
    assert m["decline"]["precision"] == pytest.approx(1.0)
    rev = m["reviewer"]
    assert rev["downgraded_concluded"] == 1
    assert rev["accuracy_downgraded"] == pytest.approx(0.0)
    assert rev["accuracy_not_downgraded"] == pytest.approx(1.0)


def test_failure_examples_rank_confident_errors_first():
    records = [
        _rec(concluded=True, verdict="concluded_benign",
             judgment_lean="benign", truth="pathogenic",
             model_prob_pathogenic=0.45),   # mild error
        _rec(concluded=True, verdict="concluded_benign",
             judgment_lean="benign", truth="pathogenic",
             model_prob_pathogenic=0.02),   # confident error
        _rec(concluded=True, verdict="concluded_pathogenic",
             judgment_lean="pathogenic", truth="pathogenic",
             model_prob_pathogenic=0.99),   # correct — excluded
    ]
    out = bench.pick_failure_examples(records, k=3)
    assert [r["model_prob_pathogenic"] for r in out] == [0.02, 0.45]
