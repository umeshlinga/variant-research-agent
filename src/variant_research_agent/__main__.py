"""CLI: python -m variant_research_agent <variant> [options]

Examples:
  python -m variant_research_agent "ARSB:c.1178A>C"
  python -m variant_research_agent "allele:20309" --offline
  python -m variant_research_agent "5:78839391:T>G" --live

Default mode is fully offline and deterministic (local data only, no
LLM). --live enables the gnomAD GraphQL and PubMed E-utilities
gatherers. The LLM layer turns itself on automatically when an
OpenAI-compatible endpoint answers (LLM_BASE_URL, default
http://localhost:8080/v1 — the Hyperspace node); --offline forces
template mode (same as VRA_OFFLINE=1).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="variant_research_agent",
                                 description="Variant in, auditable research dossier out.")
    ap.add_argument("variant", help="allele id | GENE:c.change | chr:pos:ref>alt | ClinVar name substring")
    ap.add_argument("--live", action="store_true",
                    help="enable live gnomAD GraphQL + PubMed E-utilities gatherers")
    ap.add_argument("--offline", action="store_true",
                    help="force deterministic offline mode (no LLM, no network)")
    ap.add_argument("--out", default="runs", help="output directory (default: runs/)")
    args = ap.parse_args(argv)

    if args.offline:
        os.environ["VRA_OFFLINE"] = "1"

    from .graph import run
    try:
        state = run(args.variant, out_dir=Path(args.out), live=args.live)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    gate, j = state["gate"], state["judgment"]
    verdict = ("DECLINED — insufficient evidence" if not gate["passed"]
               else f"{j['strength']} {j['lean']}-leaning evidence summary")
    print(f"Variant : {state['record']['name']}")
    print(f"Verdict : {verdict} "
          f"({gate['evidence_count']} evidence items, basis={j['basis']})")
    analyses = state.get("analyses") or []
    if analyses:
        counted = sum(1 for a in analyses if a["counts_as_evidence"])
        statuses = ", ".join(f"{a['name']}={a['status']}" for a in analyses)
        print(f"Analyses: {len(analyses)} run in sandbox, {counted} counted "
              f"as evidence ({statuses})")
    review = state.get("review") or {}
    if review:
        n_mat = sum(1 for c in review["critiques"] if c["severity"] == "material")
        line = (f"Review  : {len(review['critiques'])} critique(s), "
                f"{n_mat} material")
        if review.get("downgraded"):
            line += (f"; DOWNGRADED {review['strength_before']} -> "
                     f"{review['strength_after']}")
        print(line)
    designs = (state.get("design") or {}).get("designs") or []
    if designs:
        print(f"Designs : {len(designs)} validation experiment(s) proposed "
              f"(first: {designs[0]['assay_type']})")
    print(f"Dossier : {state['outputs']['dossier']}")
    print(f"Trace   : {state['outputs']['trace']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
