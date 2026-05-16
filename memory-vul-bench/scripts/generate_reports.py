#!/usr/bin/env python3
"""Regenerate all report outputs from the existing SQLite database."""

import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT.parent / ".env", override=False)

from pipeline.failure_analysis import generate_failure_analysis
from pipeline.report import generate_report


def main() -> None:
    db_path = _REPO_ROOT / "results" / "runs.db"
    generate_report(db_path=db_path)
    failure_paths = generate_failure_analysis(db_path=db_path)
    for failure_path in failure_paths:
        print(f"[report] Failure analysis → {failure_path}")
    print("[done] Reports regenerated in results/reports/")


if __name__ == "__main__":
    main()
