#!/usr/bin/env python3
"""Generic Compounding-Leverage Burst Queue & GCP Credit Waterline Planner.

Reads a workload list (or runs a built-in parameterized template) and computes cumulative
one-time build costs, strict API credit spend, ongoing monthly OpEx, and waterline eligibility.
Zero external dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List


SAMPLE_WORKLOADS: List[Dict[str, Any]] = [
    {
        "priority_rank": 1,
        "workload_id": "SRE-SLO-DASHBOARD",
        "title": "Unified Household SLO & Credit Waterline Dashboard",
        "one_time_cost_midpoint_usd": 7.5,
        "ongoing_monthly_opex_usd": 0.0,
        "can_run_on_included_agy_pool": True,
        "recommended_models": ["gemini-4-argon-medium", "claude-sonnet-5-5-medium"],
    },
    {
        "priority_rank": 2,
        "workload_id": "SOVEREIGN-AGENT-ACTION-GATE",
        "title": "Out-of-Model Action Gate, <KIT_*> Stripper & 25-Case tau-bench Suite",
        "one_time_cost_midpoint_usd": 9.0,
        "ongoing_monthly_opex_usd": 0.0,
        "can_run_on_included_agy_pool": True,
        "recommended_models": ["gemini-4-argon-medium", "claude-sonnet-5-5-medium"],
    },
    {
        "priority_rank": 3,
        "workload_id": "CORPUS-BACKFILL-BATCH",
        "title": "Historical Email & Document Multimodal Backfill (Batch API)",
        "one_time_cost_midpoint_usd": 30.0,
        "ongoing_monthly_opex_usd": 1.25,
        "can_run_on_included_agy_pool": False,
        "recommended_models": ["gemini-3.8-flash-low", "gemini-4-argon-medium"],
    },
]


def evaluate_queue(workloads: List[Dict[str, Any]], waterline_usd: float) -> Dict[str, Any]:
    cum_all = 0.0
    cum_api = 0.0
    cum_opex = 0.0
    eligible: List[str] = []
    queued: List[str] = []

    for w in workloads:
        mid = float(w["one_time_cost_midpoint_usd"])
        cum_all += mid
        if not w.get("can_run_on_included_agy_pool", False):
            cum_api += mid
        cum_opex += float(w.get("ongoing_monthly_opex_usd", 0.0))
        if cum_all <= waterline_usd or w.get("can_run_on_included_agy_pool", False):
            eligible.append(w["workload_id"])
        else:
            queued.append(w["workload_id"])

    return {
        "waterline_usd": waterline_usd,
        "total_workloads": len(workloads),
        "cumulative_all_bursts_midpoint_usd": round(cum_all, 2),
        "strict_gcp_api_credit_midpoint_usd": round(cum_api, 2),
        "cumulative_ongoing_monthly_opex_usd": round(cum_opex, 2),
        "eligible_now": eligible,
        "paused_at_waterline": queued,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate burst queue against credit waterline")
    parser.add_argument("--waterline-usd", type=float, default=100.0)
    args = parser.parse_args()
    summary = evaluate_queue(SAMPLE_WORKLOADS, args.waterline_usd)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
