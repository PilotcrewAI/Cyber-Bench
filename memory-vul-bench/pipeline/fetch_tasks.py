"""Download task metadata from the CyberGym HuggingFace dataset.

Note: ground-truth crash inputs are NOT stored in the dataset — they are baked
into each n132/arvo:{id}-vul Docker image at /tmp/poc. GT verification is done
by running the container as-is (no local PoC file required).

What this module downloads:
  - description.txt  — official vulnerability description
  - error.txt        — ASAN/UBSan crash report (useful for agent context)
  - patch.diff       — the security fix (optional context)
  - repo-vul.tar.gz  — vulnerable source (extracts key C/C++ files for agent)
"""

import json
import os
import tarfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import dotenv_values, load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_PROJECT_ROOT.parent / ".env", override=False)
if not os.environ.get("HF_TOKEN"):
    parent_env = dotenv_values(_PROJECT_ROOT.parent / ".env")
    hf_token = parent_env.get("HF_TOKEN")
    if hf_token:
        os.environ["HF_TOKEN"] = hf_token

TASKS_DIR = Path(__file__).parent.parent / "tasks"

TASK_MAP: Dict[str, Dict[str, str]] = {
    "arvo:1273": {
        "task_id": "arvo:1273",
        "arvo_id": "1273",
        "program": "wireshark",
        "crash_type": "Heap-buffer-overflow READ 1",
        "description_file": "tasks/task_001/description.txt",
        "src_dir": "tasks/task_001/src",
        "error_file": "tasks/task_001/error.txt",
        "dir": "task_001",
    },
    "arvo:1972": {
        "task_id": "arvo:1972",
        "arvo_id": "1972",
        "program": "libxml2",
        "crash_type": "Stack-buffer-overflow WRITE",
        "description_file": "tasks/task_002/description.txt",
        "src_dir": "tasks/task_002/src",
        "error_file": "tasks/task_002/error.txt",
        "dir": "task_002",
    },
    "arvo:1076": {
        "task_id": "arvo:1076",
        "arvo_id": "1076",
        "program": "libxml2",
        "crash_type": "Use-of-uninitialized-value",
        "description_file": "tasks/task_003/description.txt",
        "src_dir": "tasks/task_003/src",
        "error_file": "tasks/task_003/error.txt",
        "dir": "task_003",
    },
    "arvo:2124": {
        "task_id": "arvo:2124",
        "arvo_id": "2124",
        "program": "libxml2",
        "crash_type": "Use-of-uninitialized-value",
        "description_file": "tasks/task_004/description.txt",
        "src_dir": "tasks/task_004/src",
        "error_file": "tasks/task_004/error.txt",
        "dir": "task_004",
    },
}

DATASET_REPO = "sunblaze-ucb/cybergym"


def fetch_all(hf_token: Optional[str] = None) -> None:
    token = hf_token or os.environ.get("HF_TOKEN") or None
    for task_id, meta in TASK_MAP.items():
        print(f"[fetch] {task_id} ...", end=" ", flush=True)
        try:
            _fetch_one(meta["arvo_id"], meta["dir"], token)
            print("OK")
        except Exception as exc:
            print(f"FAILED — {exc}")


def _fetch_one(arvo_id: str, task_dir_name: str, token: Optional[str]) -> None:
    from huggingface_hub import hf_hub_download

    task_dir = TASKS_DIR / task_dir_name
    task_dir.mkdir(parents=True, exist_ok=True)

    base = f"data/arvo/{arvo_id}"

    # description.txt
    _download_file(hf_hub_download, DATASET_REPO, f"{base}/description.txt",
                   task_dir / "hf_description.txt", token)

    # error.txt (crash report — useful context for agent)
    _download_file(hf_hub_download, DATASET_REPO, f"{base}/error.txt",
                   task_dir / "hf_error.txt", token)

    # patch.diff
    _download_file(hf_hub_download, DATASET_REPO, f"{base}/patch.diff",
                   task_dir / "hf_patch.diff", token)

    # repo-vul.tar.gz → extract source files
    src_tarball = task_dir / "repo-vul.tar.gz"
    if not src_tarball.exists():
        _download_file(hf_hub_download, DATASET_REPO, f"{base}/repo-vul.tar.gz",
                       src_tarball, token)
        if src_tarball.exists():
            _extract_src(src_tarball, task_dir)


def _download_file(hf_hub_download_fn, repo_id, filename, dest: Path,
                   token: Optional[str]) -> bool:
    import shutil
    try:
        local = hf_hub_download_fn(
            repo_id=repo_id, filename=filename,
            repo_type="dataset", token=token,
        )
        shutil.copy(local, dest)
        return True
    except Exception:
        return False


def _extract_src(tarball: Path, dest_dir: Path) -> None:
    """Extract a capped subset of C/C++ source files for agent context."""
    src_dir = dest_dir / "src"
    src_dir.mkdir(exist_ok=True)

    extensions = {".c", ".cpp", ".h", ".cc", ".cxx"}
    max_files = 30
    count = 0

    try:
        with tarfile.open(tarball, "r:gz") as tf:
            for member in tf.getmembers():
                if count >= max_files:
                    break
                if not member.isfile():
                    continue
                if Path(member.name).suffix.lower() not in extensions:
                    continue
                out_name = member.name.replace("/", "__")
                out_path = src_dir / out_name
                fobj = tf.extractfile(member)
                if fobj:
                    out_path.write_bytes(fobj.read())
                    count += 1
    except Exception as exc:
        print(f"  [warn] source extraction failed: {exc}")


def load_task_config(task_id_or_dir: str) -> Dict[str, Any]:
    """Load task.json for a given task_id (e.g., 'arvo:3848') or dir name."""
    if task_id_or_dir.startswith("arvo:"):
        meta = TASK_MAP.get(task_id_or_dir)
        if not meta:
            raise ValueError(f"Unknown task_id: {task_id_or_dir}")
        task_dir = TASKS_DIR / meta["dir"]
    else:
        task_dir = TASKS_DIR / task_id_or_dir

    task_json = task_dir / "task.json"
    if not task_json.exists():
        raise FileNotFoundError(f"task.json not found: {task_json}")

    config = json.loads(task_json.read_text())
    config["task_dir"] = str(task_dir)

    # Use HuggingFace-downloaded description if available, else fall back to local
    hf_desc = task_dir / "hf_description.txt"
    hf_error = task_dir / "hf_error.txt"
    config["description_file"] = str(hf_desc if hf_desc.exists() else task_dir / "description.txt")
    config["error_file"] = str(hf_error) if hf_error.exists() else None
    config["src_dir"] = str(task_dir / "src")
    return config


def all_task_configs() -> List[Dict[str, Any]]:
    return [load_task_config(tid) for tid in TASK_MAP]
