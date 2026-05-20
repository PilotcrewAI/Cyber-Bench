from __future__ import annotations

import re
from pathlib import Path


SHARED_TASK_ID = "web-5"

INDIVIDUAL_TASK_IDS = (
    "co2",
    "lost-transliteration",
    "mythos-perl",
    "sniffy",
    "webpage-to-pdf-1",
)


def all_task_paths() -> tuple[Path, ...]:
    shared = [
        Path("harbor/tasks/shared") / SHARED_TASK_ID / f"l{level}"
        for level in range(0, 5)
    ]
    individual = [
        Path("harbor/tasks/individual") / task / f"l{level}"
        for task in INDIVIDUAL_TASK_IDS
        for level in range(0, 5)
    ]
    return tuple(shared + individual)


def test_checked_harbor_tasks_exist() -> None:
    for task_dir in all_task_paths():
        assert (task_dir / "instruction.md").exists()
        assert (task_dir / "task.toml").exists()
        assert (task_dir / "environment/Dockerfile").exists()
        assert (task_dir / "environment/docker-compose.yaml").exists()
        assert (task_dir / "environment/gateway.py").exists()
        assert (task_dir / "tests/test.sh").exists()
        assert (task_dir / "tests/grade_flags.py").exists()
        assert (task_dir / "solution/solve.sh").exists()


def test_web_5_harbor_task_has_shared_environment() -> None:
    compose = Path("harbor/tasks/shared/web-5/l0/environment/docker-compose.yaml").read_text()

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
    compose = Path("harbor/tasks/individual/co2/l0/environment/docker-compose.yaml").read_text()

    assert "ductf-2024-co2:" in compose
    assert "ductf-2024-sniffy:" not in compose
    assert "gctf-2025-mythos-perl:" not in compose
    assert "8111" in compose


def test_harbor_tasks_use_file_based_grading_contract() -> None:
    for task_dir in all_task_paths():
        instruction = (task_dir / "instruction.md").read_text()
        grader = (task_dir / "tests/grade_flags.py").read_text()

        assert "/app/flags.txt" in instruction
        assert "/logs/verifier/reward.txt" in grader
        assert "submit_flag" not in instruction


def test_harbor_task_build_contexts_resolve_from_environment_dir() -> None:
    context_pattern = re.compile(r'context:\s+"([^"]+)"')

    for task_dir in all_task_paths():
        environment_dir = task_dir / "environment"
        compose = (environment_dir / "docker-compose.yaml").read_text()
        for context in context_pattern.findall(compose):
            if context.startswith("."):
                assert (environment_dir / context).resolve().exists()


def test_web_5_hint_level_tasks_are_nested_and_cumulative() -> None:
    task_root = Path("harbor/tasks/shared/web-5")
    assert not (task_root / "instruction.md").exists()
    assert not (task_root / "task.toml").exists()
    assert not tuple(Path("harbor/tasks/shared").glob("web-5-l*"))
    assert not (task_root / "l5").exists()

    base = (task_root / "l0/instruction.md").read_text()
    task_toml = (task_root / "l0/task.toml").read_text()
    assert "## Hints" not in base
    assert "hint_level = 0" in task_toml

    for level in range(1, 5):
        instruction = (task_root / f"l{level}/instruction.md").read_text()
        task_toml = (task_root / f"l{level}/task.toml").read_text()

        assert "## Hints" in instruction
        assert f"hint_level = {level}" in task_toml
        for included in range(1, level + 1):
            assert f"Hint {included}:" in instruction
        for excluded in range(level + 1, 5):
            assert f"Hint {excluded}:" not in instruction


def test_individual_hint_level_tasks_are_nested_and_cumulative() -> None:
    for task in INDIVIDUAL_TASK_IDS:
        task_root = Path("harbor/tasks/individual") / task
        assert not (task_root / "instruction.md").exists()
        assert not (task_root / "task.toml").exists()
        assert not (task_root / "l5").exists()

        l0_instruction = (task_root / "l0/instruction.md").read_text()
        l0_toml = (task_root / "l0/task.toml").read_text()
        assert "## Hints" not in l0_instruction
        assert "hint_level = 0" in l0_toml

        for level in range(1, 5):
            instruction = (task_root / f"l{level}/instruction.md").read_text()
            task_toml = (task_root / f"l{level}/task.toml").read_text()
            assert "## Hints" in instruction
            assert f"hint_level = {level}" in task_toml
            for included in range(1, level + 1):
                assert f"Hint {included}:" in instruction
            for excluded in range(level + 1, 5):
                assert f"Hint {excluded}:" not in instruction
