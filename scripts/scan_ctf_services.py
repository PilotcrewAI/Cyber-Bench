from __future__ import annotations

import argparse
import json
from pathlib import Path


WEB_HINTS = {
    "web",
    "http",
    "xss",
    "sqli",
    "sql",
    "flask",
    "django",
    "php",
    "node",
    "express",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan downloaded CTF archives for candidate web services.")
    parser.add_argument("--asset-root", type=Path, default=Path("resources/ctf-archives"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    candidates = list(scan(args.asset_root))
    if args.json:
        print(json.dumps(candidates, indent=2, sort_keys=True))
    else:
        for candidate in candidates:
            print(f"{candidate['source_id']}: {candidate['path']} ({', '.join(candidate['evidence'])})")
    return 0


def scan(asset_root: Path):
    if not asset_root.exists():
        return
    for source_dir in sorted(path for path in asset_root.iterdir() if path.is_dir()):
        for directory in sorted(path for path in source_dir.rglob("*") if path.is_dir()):
            evidence = service_evidence(directory)
            if evidence and looks_webby(directory):
                yield {
                    "source_id": source_dir.name,
                    "path": str(directory.relative_to(asset_root)),
                    "evidence": evidence,
                }


def service_evidence(directory: Path) -> list[str]:
    evidence: list[str] = []
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (directory / name).exists():
            evidence.append(name)
    return evidence


def looks_webby(directory: Path) -> bool:
    parts = {part.lower() for part in directory.parts}
    if parts & WEB_HINTS:
        return True
    joined = " ".join(parts)
    return any(hint in joined for hint in WEB_HINTS)


if __name__ == "__main__":
    raise SystemExit(main())
