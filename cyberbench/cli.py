from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cyberbench.config import (
    load_dotenv,
    local_timestamp_slug,
    path_slug,
    require_openrouter_key,
    resolve_model,
)
from cyberbench.manifest import load_manifest, validate_manifest
from cyberbench.openrouter import OpenRouterClient, first_message
from cyberbench.runner import AgentRunner
from cyberbench.runtime.docker import DEFAULT_ATTACKER_IMAGE, DockerRuntime


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="cyberbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-config")

    check = subparsers.add_parser("check-openrouter")
    check.add_argument(
        "--model",
        default=None,
        help="OpenRouter model id (overrides CYBERBENCH_MODEL; default otherwise).",
    )

    validate = subparsers.add_parser("validate-bundle")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--strict", action="store_true")

    prepare = subparsers.add_parser("prepare-run")
    prepare.add_argument("manifest", type=Path)

    run = subparsers.add_parser("run")
    run.add_argument("manifest", type=Path)
    run.add_argument(
        "--model",
        default=None,
        help="OpenRouter model id (overrides CYBERBENCH_MODEL; default otherwise).",
    )
    run.add_argument("--attacker-image", default=DEFAULT_ATTACKER_IMAGE)
    run.add_argument("--keep-containers", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "validate-config":
        return _validate_config()
    if args.command == "check-openrouter":
        return _check_openrouter(args.model)
    if args.command == "validate-bundle":
        return _validate_bundle(args.manifest, strict=args.strict)
    if args.command == "prepare-run":
        return _prepare_run(args.manifest)
    if args.command == "run":
        return _run(args)
    raise AssertionError(args.command)


def _validate_config() -> int:
    api_key = require_openrouter_key()
    model = resolve_model(None)
    print(f"OPENROUTER_API_KEY=present ({len(api_key)} chars)")
    print(f"resolved_model={model}")
    return 0


def _check_openrouter(cli_model: str | None) -> int:
    api_key = require_openrouter_key()
    selected_model = resolve_model(cli_model)
    client = OpenRouterClient(api_key)
    response = client.chat_completion(
        model=selected_model,
        messages=[
            {"role": "system", "content": "Reply with exactly: OK"},
            {"role": "user", "content": "Connectivity check."},
        ],
        max_tokens=64,
        temperature=0,
    )
    message = first_message(response)
    print(json.dumps({"model": selected_model, "content": message.get("content", "")}, indent=2))
    return 0


def _validate_bundle(path: Path, *, strict: bool) -> int:
    manifest = load_manifest(path)
    errors = validate_manifest(manifest, strict=strict)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "services": len(manifest.services),
                "scored_services": len(manifest.scored_services),
                "decoy_services": len(manifest.decoy_services),
                "target_ports": [port.port for port in manifest.target_ports],
            },
            indent=2,
        )
    )
    return 0


def _prepare_run(path: Path) -> int:
    manifest = load_manifest(path)
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    ts = local_timestamp_slug()
    bundle_dir = Path("runs") / path_slug(manifest.bundle_id)
    selected_run_dir = bundle_dir / f"{ts}_prepare"
    runtime = DockerRuntime(manifest, selected_run_dir)
    compose_path = runtime.prepare()
    print(compose_path)
    return 0


def _run(args: argparse.Namespace) -> int:
    api_key = require_openrouter_key()
    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    model = resolve_model(args.model)
    ts = local_timestamp_slug()
    bundle_dir = Path("runs") / path_slug(manifest.bundle_id)
    run_dir = bundle_dir / f"{ts}_{path_slug(model)}"
    runtime = DockerRuntime(manifest, run_dir, attacker_image=args.attacker_image)
    client = OpenRouterClient(api_key)
    runner = AgentRunner(
        manifest=manifest,
        runtime=runtime,
        client=client,
        model=model,
        run_dir=run_dir,
    )
    try:
        runtime.up()
        result = runner.run()
    finally:
        if not args.keep_containers:
            runtime.down()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"solved", "budget_exhausted", "timeout", "agent_gave_up"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
