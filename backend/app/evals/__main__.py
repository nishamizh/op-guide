"""Run the labeled evaluation set. Scores are deterministic checks, not an LLM judge.

Example:
  python -m app.evals --cases e104-meaning,unsafe-bypass
"""

import argparse
import asyncio
import json

from app.evals.runner import run_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ManualMind labeled evaluations.")
    parser.add_argument("--cases", default="", help="Comma-separated case ids. Default: the full dataset.")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--user", default="eval")
    parser.add_argument("--fail-on-unsafe", action="store_true")
    args = parser.parse_args()
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()] or None
    result = asyncio.run(run_evaluation(args.tenant, args.user, case_ids))
    print(json.dumps({"id": result["id"], "experiment": result["experiment"], "metrics": result["metrics"]}, indent=2))
    unsafe = float((result.get("metrics") or {}).get("unsafe_answer_rate") or 0)
    if args.fail_on_unsafe and unsafe > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
