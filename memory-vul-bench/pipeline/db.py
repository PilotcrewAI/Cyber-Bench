import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_PROJECT_ROOT.parent / ".env", override=False)

_DEFAULT_DB = Path(__file__).parent.parent / "results" / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    arvo_id TEXT,
    crash_type TEXT,
    description TEXT,
    gt_verified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    model TEXT,
    iteration INTEGER,
    poc_size INTEGER,
    crashed_vuln INTEGER,
    crashed_fixed INTEGER,
    agent_succeeded INTEGER,
    sanitizer_snippet TEXT,
    stop_reason TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    agent_reasoning TEXT,
    poc_b64_raw TEXT,
    poc_decode_error INTEGER,
    poc_was_empty INTEGER,
    timestamp TEXT
);
"""

_RUNS_COLUMNS: Dict[str, str] = {
    "stop_reason": "TEXT",
    "input_tokens": "INTEGER",
    "output_tokens": "INTEGER",
    "agent_reasoning": "TEXT",
    "poc_b64_raw": "TEXT",
    "poc_decode_error": "INTEGER",
    "poc_was_empty": "INTEGER",
}


def _conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or _DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def run_db_path(run_id: str) -> Path:
    return Path(__file__).parent.parent / "results" / f"runs_{run_id}.db"


def init_db(db_path: Optional[Path] = None) -> None:
    con = _conn(db_path)
    con.executescript(SCHEMA)
    _migrate_runs_table(con)
    con.commit()
    con.close()


def _migrate_runs_table(con: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in con.execute("PRAGMA table_info(runs)").fetchall()
    }
    for column, column_type in _RUNS_COLUMNS.items():
        if column not in existing:
            con.execute(f"ALTER TABLE runs ADD COLUMN {column} {column_type}")


def upsert_task(
    task_id: str,
    arvo_id: str,
    crash_type: str,
    description: str,
    db_path: Optional[Path] = None,
) -> None:
    con = _conn(db_path)
    con.execute(
        "INSERT OR REPLACE INTO tasks (task_id, arvo_id, crash_type, description) "
        "VALUES (?, ?, ?, ?)",
        (task_id, arvo_id, crash_type, description),
    )
    con.commit()
    con.close()


def mark_gt_verified(
    task_id: str,
    verified: bool = True,
    db_path: Optional[Path] = None,
) -> None:
    con = _conn(db_path)
    con.execute(
        "UPDATE tasks SET gt_verified = ? WHERE task_id = ?",
        (int(verified), task_id),
    )
    con.commit()
    con.close()


def log_run(
    task_id: str,
    model: str,
    iteration: int,
    poc_size: int,
    crashed_vuln: bool,
    crashed_fixed: bool,
    agent_succeeded: bool,
    sanitizer_snippet: str,
    stop_reason: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    agent_reasoning: str = "",
    poc_b64_raw: str = "",
    poc_decode_error: bool = False,
    poc_was_empty: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    con = _conn(db_path)
    con.execute(
        "INSERT INTO runs "
        "(task_id, model, iteration, poc_size, crashed_vuln, crashed_fixed, "
        " agent_succeeded, sanitizer_snippet, stop_reason, input_tokens, output_tokens, "
        " agent_reasoning, poc_b64_raw, poc_decode_error, poc_was_empty, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            model,
            iteration,
            poc_size,
            int(crashed_vuln),
            int(crashed_fixed),
            int(agent_succeeded),
            sanitizer_snippet,
            stop_reason,
            input_tokens,
            output_tokens,
            agent_reasoning,
            poc_b64_raw,
            int(poc_decode_error),
            int(poc_was_empty),
            datetime.utcnow().isoformat(),
        ),
    )
    con.commit()
    con.close()


def get_all_tasks(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    con = _conn(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM tasks").fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_task_runs(
    task_id: str,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    con = _conn(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM runs WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
