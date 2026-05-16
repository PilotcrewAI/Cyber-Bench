#!/usr/bin/env python3
"""Main pipeline CLI for memory-vuln-bench."""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from dotenv import dotenv_values, load_dotenv

# Ensure repo root is on sys.path regardless of invocation directory
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT.parent / ".env", override=False)
parent_env = dotenv_values(_REPO_ROOT.parent / ".env")
for env_key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "HF_TOKEN"):
    env_value = parent_env.get(env_key)
    if env_value and not os.environ.get(env_key):
        os.environ[env_key] = env_value

from pipeline import db, agent_runner, report
from pipeline.failure_analysis import generate_failure_analysis
from pipeline.fetch_tasks import all_task_configs, load_task_config, TASK_MAP
from pipeline.scorer import verify_gt

# Models to run in sequence when --model is omitted.
ALL_MODELS = [
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4-5",
]


@click.command()
@click.option("--task-id", default=None, help="Run one task only (e.g. arvo:3848)")
@click.option("--all", "run_all", is_flag=True, default=False, help="Run all 5 tasks sequentially")
@click.option("--dry-run", is_flag=True, default=False, help="Select tasks + verify GT only, no agent")
@click.option("--verify-gt", "do_verify_gt", is_flag=True, default=False, help="Run GT PoC verification only")
@click.option("--model", default=None, help="Run one specific model only (e.g. anthropic/claude-sonnet-4). If omitted runs all models.")
@click.option("--budget", default=6.0, type=float, help="Per-model budget in USD (default: 6.0)")
@click.option("--run-id", default=None, help="Run identifier for isolated DB and reports")
def main(
    task_id: Optional[str],
    run_all: bool,
    dry_run: bool,
    do_verify_gt: bool,
    model: Optional[str],
    budget: float,
    run_id: Optional[str],
) -> None:
    """Memory vulnerability benchmark pipeline."""
    active_run_id = run_id or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    db_path = db.run_db_path(active_run_id)
    output_dir = _REPO_ROOT / "results" / active_run_id / "reports"
    click.echo(f"[run] Run ID: {active_run_id}")
    click.echo(f"[run] DB: {db_path.relative_to(_REPO_ROOT)}")
    click.echo(f"[run] Reports: {output_dir.relative_to(_REPO_ROOT)}/")
    db.init_db(db_path)

    if do_verify_gt:
        tasks = [load_task_config(task_id)] if task_id else all_task_configs()
        _register_tasks(tasks, db_path)
        _run_gt_verification(tasks, db_path)
        return

    if not task_id and not run_all:
        click.echo("Specify --task-id <id>, --all, --verify-gt, or --dry-run")
        click.echo("\nAvailable task IDs:")
        for tid in TASK_MAP:
            click.echo(f"  {tid}")
        raise SystemExit(1)

    if task_id:
        tasks = [load_task_config(task_id)]
    else:
        tasks = all_task_configs()

    # Which models to run
    models_to_run = [model] if model else ALL_MODELS
    print("These are the models to run: ", models_to_run)
    _register_tasks(tasks, db_path)

    if dry_run:
        click.echo("[dry-run] Verifying GT PoCs only — no agent will run\n")
        _run_gt_verification(tasks, db_path)
        return

    # Full pipeline — run each task x each model
    results = []
    for cfg in tasks:
        tid = cfg["task_id"]

        # GT verification gate
        gt_result = verify_gt(cfg["arvo_id"])
        if gt_result.crashed_vuln:
            db.mark_gt_verified(tid, verified=True, db_path=db_path)
            click.echo(f"[gt] {tid} — PASS (GT PoC crashes vulnerable binary)")
        else:
            db.mark_gt_verified(tid, verified=False, db_path=db_path)
            msg = gt_result.sanitizer_output or "no crash detected"
            click.echo(f"[gt] {tid} — FAIL ({msg}) — skipping agent run")
            continue

        # Run each model on this task
        for current_model in models_to_run:
            click.echo(f"\n[agent] {tid} | model: {current_model}")
            outcome = agent_runner.run_task(
                cfg,
                db_path=db_path,
                model=current_model,
                budget_usd=budget,
                run_id=active_run_id,
            )
            results.append(outcome)
            _print_outcome(outcome)

    if results:
        report.generate_report(db_path=db_path, output_dir=output_dir, run_id=active_run_id)
        failure_paths = generate_failure_analysis(
            db_path=db_path,
            output_dir=output_dir,
            run_id=active_run_id,
        )
        for failure_path in failure_paths:
            click.echo(f"[report] Failure analysis → {failure_path}")
        click.echo(f"\n[done] Report saved to {output_dir.relative_to(_REPO_ROOT)}/")


def _register_tasks(tasks: List[Dict[str, Any]], db_path: Path) -> None:
    for cfg in tasks:
        db.upsert_task(
            task_id=cfg["task_id"],
            arvo_id=cfg["arvo_id"],
            crash_type=cfg["crash_type"],
            description=Path(cfg["description_file"]).read_text()
            if Path(cfg["description_file"]).exists()
            else "",
            db_path=db_path,
        )


def _run_gt_verification(tasks: List[Dict[str, Any]], db_path: Path) -> None:
    for cfg in tasks:
        tid = cfg["task_id"]
        result = verify_gt(cfg["arvo_id"])
        if result.crashed_vuln:
            db.mark_gt_verified(tid, verified=True, db_path=db_path)
            click.echo(f"[gt] {tid} — PASS")
        else:
            db.mark_gt_verified(tid, verified=False, db_path=db_path)
            snippet = result.sanitizer_output[:120] or "no crash"
            click.echo(f"[gt] {tid} — FAIL ({snippet})")


def _print_outcome(outcome: Dict[str, Any]) -> None:
    tid = outcome.get("task_id", "?")
    model = outcome.get("model", "?")
    o = outcome.get("outcome", "?")
    iters = outcome.get("iteration", 0)
    cv = "YES" if outcome.get("crashed_vuln") else "no"
    cf = "YES" if outcome.get("crashed_fixed") else "no"

    if o == "agent_succeeded":
        verdict = "AGENT_SUCCEEDED — patch MAY BE BROKEN (crashed fixed binary)"
    else:
        verdict = "AGENT_FAILED — patch CONFIRMED (fixed binary survived)"

    click.echo(
        f"\n{'='*60}\n"
        f"Task:          {tid}\n"
        f"Model:         {model}\n"
        f"Iterations:    {iters}\n"
        f"Crashed vuln:  {cv}\n"
        f"Crashed fixed: {cf}\n"
        f"Verdict:       {verdict}\n"
        f"{'='*60}"
    )


if __name__ == "__main__":
    main()