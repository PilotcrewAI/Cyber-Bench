#!/usr/bin/env python3
"""Standalone script to verify all ground-truth PoC files against Docker containers."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from pipeline import db
from pipeline.fetch_tasks import all_task_configs
from pipeline.scorer import verify_gt


def main() -> None:
    db_path = _REPO_ROOT / "results" / "runs.db"
    db.init_db(db_path)

    tasks = all_task_configs()
    passed = 0
    failed = 0

    print(f"Verifying {len(tasks)} ground-truth PoC(s)...\n")

    for cfg in tasks:
        tid = cfg["task_id"]
        arvo_id = cfg["arvo_id"]
        db.upsert_task(
            task_id=tid,
            arvo_id=arvo_id,
            crash_type=cfg["crash_type"],
            description=Path(cfg["description_file"]).read_text()
            if Path(cfg["description_file"]).exists()
            else "",
            db_path=db_path,
        )

        # GT PoC is baked into the Docker image — no local file needed
        result = verify_gt(arvo_id)

        if result.crashed_vuln:
            db.mark_gt_verified(tid, verified=True, db_path=db_path)
            fixed_str = " [also crashed fixed — BAD]" if result.crashed_fixed else ""
            print(f"  PASS  {tid}{fixed_str}")
            passed += 1
        else:
            db.mark_gt_verified(tid, verified=False, db_path=db_path)
            snippet = result.sanitizer_output[:100] or "no crash detected"
            print(f"  FAIL  {tid}  ({snippet})")
            failed += 1

    print(f"\nResults: {passed} passed / {failed} failed")
    print(f"DB updated: {db_path}")

    if failed:
        print(
            "\nHint: run `python scripts/run_pipeline.py --dry-run` after fetching tasks"
            " to ensure GT PoCs are present."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
