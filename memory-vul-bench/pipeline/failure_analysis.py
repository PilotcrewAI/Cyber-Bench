"""Generate detailed failure analysis reports from run-level logs."""

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_DB = Path(__file__).parent.parent / "results" / "runs.db"
_REPORTS_DIR = Path(__file__).parent.parent / "results" / "reports"
_BUDGET_USD = 6.0

_COST_PER_1M_INPUT = {
    "anthropic/claude-sonnet-4": 3.0,
    "anthropic/claude-opus-4-5": 15.0,
    "anthropic/claude-haiku-4-5": 0.25,
    "openai/gpt-4o": 2.5,
    "google/gemini-pro-1.5": 1.25,
}
_COST_PER_1M_OUTPUT = {
    "anthropic/claude-sonnet-4": 15.0,
    "anthropic/claude-opus-4-5": 75.0,
    "anthropic/claude-haiku-4-5": 1.25,
    "openai/gpt-4o": 10.0,
    "google/gemini-pro-1.5": 5.0,
}


def generate_failure_analysis(
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> List[Path]:
    """Generate one markdown report per model explaining failure patterns."""
    db_file = Path(db_path or _DEFAULT_DB)
    out_dir = Path(output_dir or _REPORTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_file))
    con.row_factory = sqlite3.Row
    rows = [dict(row) for row in con.execute("SELECT * FROM runs ORDER BY model, task_id, id")]
    con.close()

    grouped_by_model: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        model = str(row.get("model") or "unknown_model")
        task_id = str(row.get("task_id") or "unknown_task")
        grouped_by_model[model][task_id].append(row)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_paths: List[Path] = []
    for model in sorted(grouped_by_model):
        model_safe = _safe_model_name(model)
        report_path = out_dir / f"failure_analysis_{model_safe}_{timestamp}.md"
        report_path.write_text(_render_markdown(model, grouped_by_model[model], timestamp))
        report_paths.append(report_path)
    return report_paths


def _render_markdown(
    model: str,
    grouped_by_task: Dict[str, List[Dict[str, Any]]],
    timestamp: str,
) -> str:
    lines: List[str] = [
        f"# Failure Analysis — {model}",
        "",
        f"_Generated: {timestamp}_",
        "",
    ]

    if not grouped_by_task:
        lines.append("No run rows found.")
        return "\n".join(lines) + "\n"

    for task_id in sorted(grouped_by_task):
        runs = grouped_by_task[task_id]
        lines.extend(_render_group(task_id, model, runs))

    return "\n".join(lines) + "\n"


def _safe_model_name(model: str) -> str:
    return model.replace("/", "_").replace(".", "_")


def _render_group(task_id: str, model: str, runs: List[Dict[str, Any]]) -> List[str]:
    total = len(runs)
    stop_counts = Counter(_stop_reason(run) for run in runs)
    empty_count = sum(1 for run in runs if run.get("poc_was_empty"))
    non_empty_count = total - empty_count
    decode_error_count = sum(1 for run in runs if run.get("poc_decode_error"))
    empty_rate = empty_count / total if total else 0.0
    decode_error_rate = decode_error_count / total if total else 0.0
    total_cost = _total_cost(model, runs)
    pattern = _classify_pattern(runs, empty_rate, decode_error_rate, total_cost)
    reasoning_samples = _reasoning_samples(runs)

    lines: List[str] = [
        f"## {task_id} / `{model}`",
        "",
        "### Header",
        "",
        f"- Task ID: `{task_id}`",
        f"- Model: `{model}`",
        f"- Total iterations: {total}",
        f"- Total cost: ${total_cost:.4f}",
        "",
        "### Failure Pattern",
        "",
        pattern,
        "",
        "### Stop Reason Breakdown",
        "",
        "| Stop Reason | Count |",
        "|-------------|------:|",
    ]

    for reason, count in sorted(stop_counts.items()):
        lines.append(f"| {_md(reason)} | {count} |")

    lines.extend([
        "",
        "### Empty PoC Analysis",
        "",
        f"- Total empty submissions: {empty_count}",
        f"- Total non-empty submissions: {non_empty_count}",
        f"- Empty rate: {empty_rate:.1%}",
        f"- Decode error rate: {decode_error_rate:.1%}",
        "",
        "### Step Log",
        "",
    ])

    for run in runs:
        lines.extend([
            (
                "Iter {iteration} | size={poc_size}B | crashed_vuln={crashed_vuln} | "
                "crashed_fixed={crashed_fixed}"
            ).format(
                iteration=run.get("iteration", ""),
                poc_size=run.get("poc_size", ""),
                crashed_vuln=_tf(run.get("crashed_vuln")),
                crashed_fixed=_tf(run.get("crashed_fixed")),
            ),
            f"Reasoning: {_md(_reasoning_text(run)[:200])}",
            f"PoC preview: {_md(str(run.get('poc_b64_raw') or '')[:100])}",
            f"Stop reason: {_md(_stop_reason(run))}",
            "---",
            "",
        ])

    lines.extend([
        "### Agent Strategy Summary",
        "",
    ])
    if reasoning_samples:
        for sample in reasoning_samples:
            lines.append(f"- {_md(sample)}")
    else:
        lines.append("- No reasoning snippets logged.")
    lines.append("")
    return lines


def _classify_pattern(
    runs: List[Dict[str, Any]],
    empty_rate: float,
    decode_error_rate: float,
    total_cost: float,
) -> str:
    total = len(runs)
    stop_reasons = [_stop_reason(run) for run in runs]

    if empty_rate > 0.5:
        return "empty_pocs"
    if total < 5:
        return "stopped_early"
    if decode_error_rate > 0.3:
        return "wrong_format"
    if total_cost >= _BUDGET_USD:
        return "budget_exhausted"
    if stop_reasons and stop_reasons[-1] in {"end_turn", "stop"}:
        return "gave_up"

    return "normal_failure"


def _reasoning_samples(runs: List[Dict[str, Any]]) -> List[str]:
    samples: List[str] = []
    seen = set()
    for run in runs:
        snippet = _reasoning_text(run).strip()
        key = " ".join(snippet.lower().split())[:120]
        if not snippet or key in seen:
            continue
        seen.add(key)
        samples.append(snippet[:300])
    return samples


def _bool_mark(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _tf(value: Any) -> str:
    return "T" if bool(value) else "F"


def _total_cost(model: str, runs: List[Dict[str, Any]]) -> float:
    input_cost = _COST_PER_1M_INPUT.get(model, 3.0)
    output_cost = _COST_PER_1M_OUTPUT.get(model, 15.0)
    total = 0.0
    for run in runs:
        input_tokens = int(run.get("input_tokens") or 0)
        output_tokens = int(run.get("output_tokens") or 0)
        total += (input_tokens / 1_000_000) * input_cost
        total += (output_tokens / 1_000_000) * output_cost
    return total


def _is_legacy_row(run: Dict[str, Any]) -> bool:
    return (
        run.get("stop_reason") is None
        and run.get("agent_reasoning") is None
        and run.get("input_tokens") is None
        and run.get("output_tokens") is None
    )


def _stop_reason(run: Dict[str, Any]) -> str:
    if run.get("stop_reason"):
        return str(run["stop_reason"])
    if _is_legacy_row(run):
        return "legacy_not_logged"
    return "not_reported"


def _reasoning_text(run: Dict[str, Any]) -> str:
    if run.get("agent_reasoning"):
        return str(run["agent_reasoning"])
    if _is_legacy_row(run):
        return "legacy row: reasoning was not logged for this run"
    return ""


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
