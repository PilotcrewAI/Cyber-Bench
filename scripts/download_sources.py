from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Download public CTF source archives into resources/ctf-archives.")
    parser.add_argument("--catalog", type=Path, default=Path("sources/public_web_ctf_sources.json"))
    parser.add_argument("--source-id", action="append", default=None, help="Download only this source id; can be repeated.")
    parser.add_argument("--update", action="store_true", help="Fetch updates for already-cloned git sources.")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text())
    asset_root = Path(catalog.get("asset_root", "resources/ctf-archives"))
    asset_root.mkdir(parents=True, exist_ok=True)
    selected = set(args.source_id or [])
    for source in catalog["sources"]:
        if selected and source["id"] not in selected:
            continue
        download_source(source, asset_root, update=args.update)
    return 0


def download_source(source: dict[str, Any], asset_root: Path, *, update: bool) -> None:
    if source.get("type") != "git":
        raise ValueError(f"unsupported source type for {source['id']}: {source.get('type')}")
    destination = asset_root / source["id"]
    if destination.exists():
        if update:
            print(f"updating {source['id']} in {destination}")
            run(["git", "-C", str(destination), "fetch", "--depth", "1", "origin"])
            run(["git", "-C", str(destination), "reset", "--hard", "FETCH_HEAD"])
        else:
            print(f"exists {source['id']} at {destination}")
        return
    print(f"cloning {source['id']} -> {destination}")
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            source["url"],
            str(destination),
        ]
    )


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
