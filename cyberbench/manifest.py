from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BudgetConfig:
    command_timeout_seconds: int = 30
    max_steps: int = 1000 #Virtually infinite, but we use the max cost usd to stop the agent
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class TargetPort:
    port: int
    service_id: str


@dataclass(frozen=True)
class ServiceConfig:
    id: str
    role: str
    image: str
    container_port: int
    command: list[str] | None = None
    build_context: str | None = None
    privileged: bool = False
    mount: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    expected_flags: tuple[str, ...] = ()
    category: str = "web"

    @property
    def scored(self) -> bool:
        return self.role == "ctf"


@dataclass(frozen=True)
class BundleManifest:
    path: Path
    schema_version: int
    bundle_id: str
    description: str
    target_host: str
    target_ports: tuple[TargetPort, ...]
    services: tuple[ServiceConfig, ...]
    budgets: BudgetConfig
    levels: dict[int, str] = field(default_factory=dict)
    smoke: bool = False

    @property
    def scored_services(self) -> tuple[ServiceConfig, ...]:
        return tuple(service for service in self.services if service.scored)

    @property
    def decoy_services(self) -> tuple[ServiceConfig, ...]:
        return tuple(service for service in self.services if service.role == "decoy")


def level_hint_block(manifest: BundleManifest, level: int | None) -> str | None:
    if level is None:
        return None
    hints = [(item, manifest.levels[item]) for item in sorted(manifest.levels) if item <= level]
    if not hints:
        return None
    return "\n\n".join(f"Hint {item}:\n{hint}" for item, hint in hints)


def load_manifest(path: Path) -> BundleManifest:
    data = json.loads(path.read_text())
    services = tuple(_service(item) for item in data["services"])
    target = data["target"]
    budgets = data.get("budgets", {})
    levels = data.get("levels", {})
    return BundleManifest(
        path=path,
        schema_version=int(data["schema_version"]),
        bundle_id=data["bundle_id"],
        description=data.get("description", ""),
        target_host=target.get("host", "target"),
        target_ports=tuple(TargetPort(port=int(item["port"]), service_id=item["service_id"]) for item in target["ports"]),
        services=services,
        budgets=BudgetConfig(
            command_timeout_seconds=int(budgets.get("command_timeout_seconds", 30)),
            max_steps=int(budgets.get("max_steps", 1000)),
            max_cost_usd=_optional_float(budgets.get("max_cost_usd")),
        ),
        levels={int(level): str(hint) for level, hint in levels.items()},
        smoke=bool(data.get("smoke", False)),
    )


def validate_manifest(manifest: BundleManifest, *, strict: bool = False) -> list[str]:
    errors: list[str] = []
    service_ids = {service.id for service in manifest.services}
    if manifest.schema_version != 1:
        errors.append("schema_version must be 1")
    if len(service_ids) != len(manifest.services):
        errors.append("service ids must be unique")
    for target_port in manifest.target_ports:
        if target_port.service_id not in service_ids:
            errors.append(f"target port {target_port.port} references missing service {target_port.service_id!r}")
    for service in manifest.services:
        if service.category != "web":
            errors.append(f"service {service.id!r} is category {service.category!r}; v1 is web-only")
        if service.scored and not service.expected_flags:
            errors.append(f"scored service {service.id!r} must define expected_flags")
        if service.build_context:
            context = Path(service.build_context)
            if not context.is_absolute():
                context = (Path.cwd() / context).resolve()
            if not context.exists():
                errors.append(f"service {service.id!r} build_context does not exist: {service.build_context}")
        if service.mount:
            mount = manifest.path.parent / service.mount
            if not mount.exists():
                errors.append(f"service {service.id!r} mount does not exist: {service.mount}")
    for level, hint in manifest.levels.items():
        if level < 1:
            errors.append(f"level {level!r} must be a positive integer")
        if not hint.strip():
            errors.append(f"level {level!r} must define a non-empty hint")
    if strict and not manifest.smoke and len(manifest.scored_services) != 10:
        errors.append("strict v1 bundles must contain exactly 10 scored CTF services")
    return errors


def _service(data: dict[str, Any]) -> ServiceConfig:
    return ServiceConfig(
        id=data["id"],
        role=data["role"],
        image=data["image"],
        container_port=int(data["container_port"]),
        command=list(data["command"]) if "command" in data else None,
        build_context=data.get("build_context"),
        privileged=bool(data.get("privileged", False)),
        mount=data.get("mount"),
        env={str(k): str(v) for k, v in data.get("env", {}).items()},
        expected_flags=tuple(data.get("expected_flags", ())),
        category=data.get("category", "web"),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
