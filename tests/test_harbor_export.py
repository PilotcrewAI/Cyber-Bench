from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

from cyberbench.harbor_export import default_harbor_manifests, export_harbor_tasks


def test_export_smoke_web_harbor_task(tmp_path: Path) -> None:
    task_dirs = export_harbor_tasks(
        [Path("bundles/smoke-web/manifest.json")],
        output_root=tmp_path,
    )

    task_dir = task_dirs[0]
    assert task_dir == tmp_path / "smoke-web"
    assert (task_dir / "instruction.md").exists()
    assert (task_dir / "task.toml").read_text().startswith('schema_version = "1.1"')

    compose = (task_dir / "environment/docker-compose.yaml").read_text()
    assert "main:" in compose
    assert "target:" in compose
    assert "vuln-basic:" in compose
    assert "decoy-status:" in compose
    assert "CYBERBENCH_GATEWAY_MAP" in compose

    grader = (task_dir / "tests/grade_flags.py").read_text()
    assert "CYBERBENCH{smoke_vuln_basic}" in grader
    assert "/logs/verifier/reward.txt" in grader


def test_export_uses_relative_build_context(tmp_path: Path) -> None:
    with TemporaryDirectory(dir=Path.cwd()) as output_root:
        task_dirs = export_harbor_tasks(
            [Path("bundles/web-5/manifest.json")],
            output_root=Path(output_root),
        )

        compose = (task_dirs[0] / "environment/docker-compose.yaml").read_text()
        assert "resources/ctf-archives" in compose
        assert str(Path.cwd()) not in compose

        task_toml = (task_dirs[0] / "task.toml").read_text()
        assert 'source = "bundles/web-5/manifest.json"' in task_toml


def test_default_harbor_export_scope_is_verified_web_5() -> None:
    assert default_harbor_manifests() == [Path("bundles/web-5/manifest.json")]


def test_web_5_export_has_shared_five_service_environment(tmp_path: Path) -> None:
    task_dirs = export_harbor_tasks(
        default_harbor_manifests(),
        output_root=tmp_path,
    )

    compose = (task_dirs[0] / "environment/docker-compose.yaml").read_text()
    assert "target:" in compose
    assert "gctf-2025-lost-transliteration:" in compose
    assert "gctf-2025-mythos-perl:" in compose
    assert "ductf-2024-co2:" in compose
    assert "ductf-2024-sniffy:" in compose
    assert "hkcert-2024-webpage-to-pdf-1:" in compose
    for port in ("8102", "8103", "8111", "8112", "8113"):
        assert port in compose
