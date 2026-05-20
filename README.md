# Cyber-Bench

This repo contains Cyber-Bench and Memory Vulnerability benchmarks.

Everything related to memory-vuln-bench lives in the memory-vul-bench/ folder.

CyberExplorer-style environment: fixed curated bundles, multiple exposed web
services, scored CTF targets, and LLM agents through
OpenRouter under cost budgets.

## Prerequisites


- **Docker Engine** and the **Docker Compose V2 plugin** — `docker` and
  `docker compose` must work for `run` and `run-opencode`. Install from your OS
  or follow [Docker’s install guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

**Only for `run-opencode`:**

- **Node.js** and **npm** on the host, then `npm i -g opencode-ai@latest` so the
  `opencode` command is available (use `sudo` for `-g` if your Node install is
  system-wide).

**Useful extras:** `git` (clone), `jq` (inspect `result.json` under `runs/`).


## Configuration

Create `.env` with:

```env
OPENROUTER_API_KEY=...
```

Pick the OpenRouter model via CLI `--model`, or default it with env:

```env
CYBERBENCH_MODEL=anthropic/claude-sonnet-4.5
```

If neither is set, Cyber-Bench falls back to `anthropic/claude-sonnet-4.5`.

## Commands

Activate the local environment first:

```bash
source .venv/bin/activate
```

General CLI checks:

```bash
python -m cyberbench.cli validate-config
python -m cyberbench.cli check-openrouter
python -m cyberbench.cli check-openrouter --model openai/gpt-5-codex
python -m cyberbench.cli validate-bundle bundles/smoke-web/manifest.json
python -m cyberbench.cli prepare-run bundles/smoke-web/manifest.json
python -m cyberbench.cli run bundles/smoke-web/manifest.json
python -m cyberbench.cli run-opencode bundles/smoke-web/manifest.json
```

`run` requires Docker with the Compose plugin. It starts a target gateway,
multiple web services, and an attacker container, then gives the model only two
tools: shell execution inside the attacker container and structured flag
submission. The default attacker image is built from `python:3.12` with common
web/CTF tools installed, including `curl`, `wget`, `nmap`, `netcat`, `dnsutils`,
`jq`, and `git`.

Use OpenRouter model IDs directly:

```bash
python -m cyberbench.cli run bundles/smoke-web/manifest.json --model anthropic/claude-haiku-4.5
python -m cyberbench.cli run bundles/smoke-web/manifest.json --model openai/gpt-5.4-nano
```

### OpenCode backend

`run-opencode` uses the `opencode` CLI as the coding agent while
keeping the benchmark manifest as the source of truth for visible targets. It
starts a Docker target network, creates an empty execution workspace under
`/tmp/cyberbench-opencode/`, mounts that workspace into the attacker container,
writes two helper commands into it, and runs opencode from that isolated
directory:

- `./bench_shell '<command>'` executes inside the attacker container.
- `./submit_flag '<flag>'` submits to the Cyber-Bench scorer.

The OpenCode subprocess uses a clean per-run home/config directory, disables
project config discovery, and denies plain host bash commands except for the two
helpers above. This prevents repo-level `AGENTS.md` / `CLAUDE.md` files and
host-only commands from contaminating benchmark runs.

Install opencode separately before using this backend:

```bash
npm i -g opencode-ai@latest
```

Then run:

```bash
python -m cyberbench.cli run-opencode bundles/smoke-web/manifest.json \
  --model anthropic/claude-haiku-4.5
```

The OpenCode model id is passed as `openrouter/<model>`, so the same
OpenRouter model IDs used by the API-shell runner should be used here.
`manifest.target.ports` controls the target URLs shown to opencode, for example
`http://target:8081/`; challenge source directories are not mounted into the
opencode workspace.

Run artifacts live under `runs/<bundle_id>/<local_timestamp>_<model_slug>/`.  

```bash
jq . runs/<bundle_id>/<run-folder>/result.json
tail -n 20 runs/<bundle_id>/<run-folder>/transcript.jsonl
```

### Harbor / Terminal-Bench export

Export the verified shared Web-5 environment to Harbor task format:

```bash
python -m cyberbench.cli export-harbor-tasks --force
```

By default this writes only `harbor/tasks/web-5/` from
`bundles/web-5/manifest.json`. It does not read or modify `memory-vul-bench/`.
The generated task keeps the Cyber-Bench target gateway and all five Web-5
service sidecars, uses Harbor's `main` terminal container, and grades recovered
flags written one per line to `/app/flags.txt`. Harbor run artifacts are written
under `jobs/`.

The Web-5 Harbor compose file is the shared environment: `main` reaches the
five services through `http://target:8102`, `http://target:8103`,
`http://target:8111`, `http://target:8112`, and `http://target:8113`.

If the attacker base image is not already present locally, build it first:

```bash
docker build -t cyberbench/attacker:latest cyberbench/runtime/attacker
```

Smoke-check the generated Web-5 task with Harbor's oracle agent:

```bash
harbor run -p harbor/tasks/web-5 -a oracle
```

## Transcript viewer

For an interactive step-through of agent turns (plus the run summary from
`result.json`), start the local server and open the URL it prints:

```bash
python transcript-viewer/server.py
```

Defaults to http://127.0.0.1:8765/ and reads under `runs/`. Choose bundle and run
from the dropdowns; **Reload** re-reads files from disk. Optional flags:
`--port`, `--runs-dir`, `--repo-root` (see `python transcript-viewer/server.py --help`).

## Public Source Archives

Raw public CTF archives are configured in
`sources/public_web_ctf_sources.json` and download into
`resources/ctf-archives/`. The current five-task web bundle needs Google CTF,
DownUnderCTF 2024, and HKCERT CTF sources:

```bash
python scripts/download_sources.py --source-id google-ctf
python scripts/download_sources.py --source-id downunderctf-2024
python scripts/download_sources.py --source-id hkcert-ctf
```

## Current Five-Task Web Bundle

`bundles/web-5/manifest.json` is the current report/calibration bundle. It runs
five scored web CTF services together behind the shared `target` gateway:

| Port | Service | Source |
| ---- | ------- | ------ |
| 8102 | `gctf-2025-lost-transliteration` | Google CTF 2025 |
| 8103 | `gctf-2025-mythos-perl` | Google CTF 2025 |
| 8111 | `ductf-2024-co2` | DownUnderCTF 2024 |
| 8112 | `ductf-2024-sniffy` | DownUnderCTF 2024 |
| 8113 | `hkcert-2024-webpage-to-pdf-1` | HKCERT CTF 2024 |

After downloading the required public source archives, validate and prepare the
bundle:

```bash
python -m cyberbench.cli validate-bundle bundles/web-5/manifest.json --strict
COMPOSE=$(python -m cyberbench.cli prepare-run bundles/web-5/manifest.json)
docker compose -f "$COMPOSE" build
```

Run the current bundle with or without cumulative hint levels. Level 0 means omit
`--level`; level 4 exposes all hints from levels 1 through 4:

```bash
python -m cyberbench.cli run bundles/web-5/manifest.json \
  --model openai/gpt-5.5 --level 4

python -m cyberbench.cli run-opencode bundles/web-5/manifest.json \
  --model openai/gpt-5.5 --level 4
```

`prepare-run` prints the path to the generated `compose.yml` under
`runs/<bundle_id>/<local_timestamp>_prepare/` (same local `YYYYMMDD_HHMMSS` as `run`).

The original upstream image references or URLs are kept in manifest `source`
metadata for provenance. Raw source archives stay under ignored
`resources/ctf-archives/`.


The original upstream image references are still kept in the manifest `source`
metadata for provenance.

Run the curated bundle with run and run-opencode (each invocation creates a new run folder under `runs/<bundle_id>/`):

```bash
python -m cyberbench.cli run bundles/individial_tasks/lost-transliteration/lost-transliteration.json \
  --model anthropic/claude-haiku-4.5

python -m cyberbench.cli run-opencode bundles/individial_tasks/lost-transliteration/lost-transliteration.json \
  --model anthropic/claude-haiku-4.5
```

## Assets

Raw public CTF downloads belong under ignored `resources/ctf-archives/`.
Committed files should be normalized manifests, import scripts, runner code, and
documentation only.
