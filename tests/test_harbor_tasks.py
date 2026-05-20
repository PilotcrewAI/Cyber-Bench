from __future__ import annotations

from pathlib import Path


TASKS = (
    "web-5",
    "web-5-l1",
    "web-5-l2",
    "web-5-l3",
    "web-5-l4",
    "co2",
    "lost-transliteration",
    "mythos-perl",
    "sniffy",
    "webpage-to-pdf-1",
)


def test_checked_harbor_tasks_exist() -> None:
    for task in TASKS:
        task_dir = Path("harbor/tasks") / task
        assert (task_dir / "instruction.md").exists()
        assert (task_dir / "task.toml").exists()
        assert (task_dir / "environment/Dockerfile").exists()
        assert (task_dir / "environment/docker-compose.yaml").exists()
        assert (task_dir / "environment/gateway.py").exists()
        assert (task_dir / "tests/test.sh").exists()
        assert (task_dir / "tests/grade_flags.py").exists()
        assert (task_dir / "solution/solve.sh").exists()


def test_web_5_harbor_task_has_shared_environment() -> None:
    compose = Path("harbor/tasks/web-5/environment/docker-compose.yaml").read_text()

    assert "main:" in compose
    assert "target:" in compose
    assert "gctf-2025-lost-transliteration:" in compose
    assert "gctf-2025-mythos-perl:" in compose
    assert "ductf-2024-co2:" in compose
    assert "ductf-2024-sniffy:" in compose
    assert "hkcert-2024-webpage-to-pdf-1:" in compose
    for port in ("8102", "8103", "8111", "8112", "8113"):
        assert port in compose


def test_individual_harbor_task_contains_only_its_service() -> None:
    compose = Path("harbor/tasks/co2/environment/docker-compose.yaml").read_text()

    assert "ductf-2024-co2:" in compose
    assert "ductf-2024-sniffy:" not in compose
    assert "gctf-2025-mythos-perl:" not in compose
    assert "8111" in compose


def test_harbor_tasks_use_file_based_grading_contract() -> None:
    for task in TASKS:
        task_dir = Path("harbor/tasks") / task
        instruction = (task_dir / "instruction.md").read_text()
        grader = (task_dir / "tests/grade_flags.py").read_text()

        assert "/app/flags.txt" in instruction
        assert "/logs/verifier/reward.txt" in grader
        assert "submit_flag" not in instruction


def test_web_5_hint_level_tasks_are_cumulative_without_l0() -> None:
    assert not Path("harbor/tasks/web-5-l0").exists()

    base = Path("harbor/tasks/web-5/instruction.md").read_text()
    assert "## Hints" not in base

    for level in range(1, 5):
        instruction = Path(f"harbor/tasks/web-5-l{level}/instruction.md").read_text()
        task_toml = Path(f"harbor/tasks/web-5-l{level}/task.toml").read_text()

        assert "## Hints" in instruction
        assert f"hint_level = {level}" in task_toml
        for included in range(1, level + 1):
            assert f"Hint {included}:" in instruction
        for excluded in range(level + 1, 5):
            assert f"Hint {excluded}:" not in instruction
