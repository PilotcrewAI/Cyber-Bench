from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from cyberbench.manifest import BundleManifest, ServiceConfig

DEFAULT_ATTACKER_IMAGE = "cyberbench/attacker:latest"


@dataclass(frozen=True)
class ShellResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_seconds: float


class DockerRuntime:
    def __init__(
        self,
        manifest: BundleManifest,
        run_dir: Path,
        *,
        attacker_image: str = DEFAULT_ATTACKER_IMAGE,
        attacker_workspace: Path | None = None,
        publish_target_ports: bool = False,
    ) -> None:
        self.manifest = manifest
        self.run_dir = run_dir
        self.project = f"cyberbench_{manifest.bundle_id.replace('-', '_')}_{int(time.time())}"
        self.attacker_image = attacker_image
        self.attacker_workspace = attacker_workspace
        self.publish_target_ports = publish_target_ports
        self.compose_path = run_dir / "compose.yml"

    def prepare(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.compose_path.write_text(self._compose_text())
        return self.compose_path

    def up(self) -> None:
        self.prepare()
        self._run(["docker", "compose", "-f", str(self.compose_path), "-p", self.project, "up", "-d", "--remove-orphans"])

    def down(self) -> None:
        self._run(["docker", "compose", "-f", str(self.compose_path), "-p", self.project, "down", "-v"], check=False)

    def persist_helper_logs(self) -> list[Path]:
        helper_services = [service for service in self.manifest.services if service.role == "helper"]
        if not helper_services:
            return []

        log_dir = self.run_dir / "helper-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for service in helper_services:
            path = log_dir / f"{service.id}.log"
            try:
                completed = self._run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(self.compose_path),
                        "-p",
                        self.project,
                        "logs",
                        "--no-color",
                        service.id,
                    ],
                    check=False,
                )
                content = completed.stdout
                if completed.stderr:
                    content += ("\n" if content and not content.endswith("\n") else "") + completed.stderr
                if completed.returncode != 0:
                    content = f"docker compose logs exited with code {completed.returncode}\n\n{content}"
            except OSError as exc:
                content = f"failed to collect helper logs: {exc}\n"
            path.write_text(content)
            paths.append(path)
        return paths

    def exec_shell(self, command: str, *, timeout_seconds: int, output_limit: int = 20000) -> ShellResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self.compose_path),
                    "-p",
                    self.project,
                    "exec",
                    "-T",
                    "attacker",
                    "/bin/sh",
                    "-lc",
                    command,
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            timed_out = False
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = _to_text(exc.stdout)
            stderr = _to_text(exc.stderr)
        elapsed = time.monotonic() - started
        return ShellResult(
            command=command,
            exit_code=exit_code,
            stdout=_limit(stdout, output_limit),
            stderr=_limit(stderr, output_limit),
            timed_out=timed_out,
            elapsed_seconds=elapsed,
        )

    def _compose_text(self) -> str:
        attacker: dict[str, object] = {
            "image": self.attacker_image,
            "command": ["sh", "-lc", "sleep infinity"],
            "working_dir": "/workspace",
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "networks": ["bench"],
        }
        if self.attacker_workspace is not None:
            attacker["volumes"] = [f"{self.attacker_workspace.resolve()}:/workspace"]
        if self.attacker_image == DEFAULT_ATTACKER_IMAGE:
            attacker["build"] = {"context": str(_repo_root() / "cyberbench/runtime/attacker")}
        target: dict[str, object] = {
            "image": "python:3.12",
            "command": ["python", "/opt/cyberbench/gateway.py"],
            "environment": {
                "CYBERBENCH_GATEWAY_MAP": json.dumps(self._gateway_map()),
            },
            "volumes": [f"{_repo_root() / 'cyberbench/runtime/gateway.py'}:/opt/cyberbench/gateway.py:ro"],
            "depends_on": [service.id for service in self.manifest.services],
            "networks": ["bench"],
        }
        if self.publish_target_ports:
            target["ports"] = [
                f"127.0.0.1:{target_port.port}:{target_port.port}" for target_port in self.manifest.target_ports
            ]
        services: dict[str, object] = {
            "attacker": attacker,
            "target": target,
        }
        for service in self.manifest.services:
            services[service.id] = self._service_compose(service)
        return _dump_compose({"services": services, "networks": {"bench": {}}})

    def _service_compose(self, service: ServiceConfig) -> dict[str, object]:
        item: dict[str, object] = {
            "image": service.image,
            "expose": [str(service.container_port)],
            "networks": ["bench"],
        }
        if service.build_context:
            context = Path(service.build_context)
            if not context.is_absolute():
                context = (_repo_root() / context).resolve()
            item["build"] = {"context": str(context)}
        if service.privileged:
            item["privileged"] = True
        if service.command:
            item["command"] = service.command
        if service.env:
            item["environment"] = service.env
        if service.mount:
            source = (self.manifest.path.parent / service.mount).resolve()
            item["volumes"] = [f"{source}:/app:ro"]
            item["working_dir"] = "/app"
        return item

    def _gateway_map(self) -> dict[str, dict[str, object]]:
        by_service = {service.id: service for service in self.manifest.services}
        mapping: dict[str, dict[str, object]] = {}
        for target_port in self.manifest.target_ports:
            service = by_service[target_port.service_id]
            mapping[str(target_port.port)] = {"host": service.id, "port": service.container_port}
        return mapping

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=check,
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _limit(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _dump_compose(data: dict[str, object], indent: int = 0) -> str:
    lines: list[str] = []
    for key, value in data.items():
        prefix = " " * indent
        if isinstance(value, dict):
            if value:
                lines.append(f"{prefix}{key}:")
                lines.append(_dump_compose(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {{}}")
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(_dump_compose(item, indent + 4))
                else:
                    lines.append(f"{prefix}  - {json.dumps(item)}")
        else:
            lines.append(f"{prefix}{key}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"
