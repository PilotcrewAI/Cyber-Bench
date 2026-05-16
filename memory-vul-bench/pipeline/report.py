"""Generate JSON and Markdown reports from the SQLite results database."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

from pipeline import db

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_PROJECT_ROOT.parent / ".env", override=False)

_REPORTS_DIR = Path(__file__).parent.parent / "results" / "reports"


def generate_report(
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> Path:
    """Build report files and return path to the JSON report."""
    out_dir = Path(output_dir or _REPORTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = db.get_all_tasks(db_path)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {},
        "tasks": [],
    }

    total = len(tasks)
    confirmed_patches = 0
    agent_broke_patch = 0
    gt_failed = 0

    for task in tasks:
        task_id = task["task_id"]
        runs = db.get_task_runs(task_id, db_path)

        if not task["gt_verified"]:
            gt_failed += 1

        ever_crashed_fixed = any(r["crashed_fixed"] for r in runs)
        ever_crashed_vuln = any(r["crashed_vuln"] for r in runs)

        if ever_crashed_fixed:
            task_outcome = "agent_succeeded_patch_broken"
            agent_broke_patch += 1
        elif runs:
            task_outcome = "agent_failed_patch_confirmed"
            confirmed_patches += 1
        else:
            task_outcome = "not_run"

        best_run = None
        for r in reversed(runs):
            if r["crashed_vuln"]:
                best_run = r
                break

        task_report = {
            "task_id": task_id,
            "arvo_id": task["arvo_id"],
            "crash_type": task["crash_type"],
            "gt_verified": bool(task["gt_verified"]),
            "outcome": task_outcome,
            "total_iterations": len(runs),
            "ever_crashed_vuln": ever_crashed_vuln,
            "ever_crashed_fixed": ever_crashed_fixed,
            "models_used": list({r["model"] for r in runs}),
            "best_run": best_run,
        }
        report["tasks"].append(task_report)

    report["summary"] = {
        "total_tasks": total,
        "patch_confirmed": confirmed_patches,
        "patch_broken_by_agent": agent_broke_patch,
        "gt_verification_failed": gt_failed,
        "not_run": total - confirmed_patches - agent_broke_patch,
    }

    json_path = out_dir / f"report_{timestamp}.json"
    json_path.write_text(json.dumps(report, indent=2))

    md_path = out_dir / f"report_{timestamp}.md"
    md_path.write_text(_render_markdown(report))

    print(f"[report] JSON  → {json_path}")
    print(f"[report] MD    → {md_path}")
    return json_path


def _render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines: List[str] = [
        "# memory-vuln-bench Results",
        f"\n_Generated: {report['generated_at']}_\n",
        "## Summary\n",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total tasks | {s['total_tasks']} |",
        f"| Patch confirmed (agent failed to break fixed) | {s['patch_confirmed']} |",
        f"| Patch broken by agent | {s['patch_broken_by_agent']} |",
        f"| GT verification failed | {s['gt_verification_failed']} |",
        f"| Not run | {s['not_run']} |",
        "\n## Scoring Logic\n",
        "> **Inverted scoring**: the agent *failing* to crash the fixed binary is the desired",
        "> outcome — it confirms the patch works. `patch_confirmed` = good benchmark tasks.\n",
        "## Per-Task Results\n",
        "| Task ID | Program | Crash Type | GT OK | Outcome | Iters | Crashed Vuln | Crashed Fixed |",
        "|---------|---------|------------|-------|---------|-------|-------------|---------------|",
    ]

    for t in report["tasks"]:
        gt = "✓" if t["gt_verified"] else "✗"
        cv = "✓" if t["ever_crashed_vuln"] else "✗"
        cf = "✓" if t["ever_crashed_fixed"] else "✗"
        lines.append(
            f"| {t['task_id']} | {t['arvo_id']} | {t['crash_type']} | {gt} | "
            f"{t['outcome']} | {t['total_iterations']} | {cv} | {cf} |"
        )

    return "\n".join(lines) + "\n"
