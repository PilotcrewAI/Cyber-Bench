# Cyber-Bench

This repo contains Cyber-Bench and Memory Vulnerability benchmarks.

Everything related to memory-vuln-bench lives in the memory-vul-bench/ folder.

CyberExplorer-style environment: multiple exposed web services, scored CTF
targets, and LLM agents under cost budgets.

**Web CTF task development uses Harbor / Terminal-Bench.** Checked task
directories live under `harbor/tasks/` and are the canonical format for defining,
calibrating, and running the current Web-5 benchmark set. The legacy manifest
runner (`bundles/*/manifest.json`, `cyberbench.cli run`) remains available as a
fallback; see [Legacy manifest runner](#legacy-manifest-runner-fallback).

## Prerequisites


- **Docker Engine** and the **Docker Compose V2 plugin** — required for Harbor
  task environments and the legacy manifest runner. Install from your OS or
  follow [Docker’s install guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
- **Harbor CLI** — required for the canonical task workflow (`harbor run ...`).

**Only for the legacy `run-opencode` fallback:**

- **Node.js** and **npm** on the host, then `npm i -g opencode-ai@latest` so the
  `opencode` command is available (use `sudo` for `-g` if your Node install is
  system-wide).

**Useful extras:** `git` (clone), `jq` (inspect `result.json` under `runs/`).


## Configuration

Used by the legacy manifest runner and OpenCode fallback. Harbor agent
configuration is handled by Harbor itself.

Create `.env` with:

```env
OPENROUTER_API_KEY=...
```

Pick the OpenRouter model via CLI `--model`, or default it with env:

```env
CYBERBENCH_MODEL=anthropic/claude-sonnet-4.5
```

If neither is set, Cyber-Bench falls back to `anthropic/claude-sonnet-4.5`.

## Harbor / Terminal-Bench tasks

Checked task directories under `harbor/tasks/` are the **canonical** Web-5
benchmark format. Edit them directly when changing instructions, Compose
services, verifiers, or oracle solutions. Run them with Harbor; artifacts go
under `jobs/`.

Each task uses Harbor's `main` terminal container (based on
`cyberbench/attacker:latest`), the shared `target` gateway, and file-based
grading via `/app/flags.txt`. These tasks do not read or modify
`memory-vul-bench/`.

| Harbor task | Scope |
| ----------- | ----- |
| `harbor/tasks/shared/web-5/l0/` … `l4/` | All five services, no hints through cumulative level 4 |
| `harbor/tasks/individual/co2/l0/` … `l4/` | CO2 only, no hints through cumulative level 4 |
| `harbor/tasks/individual/lost-transliteration/l0/` … `l4/` | Lost Transliteration only, no hints through cumulative level 4 |
| `harbor/tasks/individual/mythos-perl/l0/` … `l4/` | Mythos Perl only, no hints through cumulative level 4 |
| `harbor/tasks/individual/sniffy/l0/` … `l4/` | Sniffy only, no hints through cumulative level 4 |
| `harbor/tasks/individual/webpage-to-pdf-1/l0/` … `l4/` | Webpage to PDF 1 only, no hints through cumulative level 4 |

Shared and individual tasks both use explicit `l0` through `l4` directories.
Hint levels are separate directories because Harbor has no native hint-level
field; each `lN/instruction.md` bakes in the cumulative hint text directly.

The shared `web-5` environment reaches five services through
`http://target:8102`, `http://target:8103`, `http://target:8111`,
`http://target:8112`, and `http://target:8113`. Individual tasks include only
their own scored service.

Build the attacker base image once if it is not already present locally:

```bash
docker build -t cyberbench/attacker:latest cyberbench/runtime/attacker
```

Warm all current Web-5 images once before model runs:

```bash
source .venv/bin/activate
docker build -t cyberbench/attacker:latest cyberbench/runtime/attacker
docker pull python:3.12
COMPOSE=$(python -m cyberbench.cli prepare-run bundles/web-5/manifest.json)
docker compose -f "$COMPOSE" build

harbor run --path harbor/tasks/shared/web-5/l0 --agent oracle --force-build
```

Oracle runs validate environment and verifier wiring via `solution/solve.sh`;
they do not measure model capability.

Run Web-5 with Harbor's Terminus-2 model agent:

```bash
source .venv/bin/activate
set -a && source .env && set +a

harbor run \
  --path harbor/tasks/shared/web-5/l4 \
  --agent terminus-2 \
  --model openrouter/openai/gpt-5.5
```

Harbor writes these run artifacts under `jobs/`. The Web-5 Harbor tasks
set `agent.timeout_sec = 3600.0`, so each attempt gets a 60 minute agent time budget.

See `docs/architecture.md` for container topology and grading flow diagrams.

## Current Web-5 task set

| Port | Service | Source |
| ---- | ------- | ------ |
| 8102 | `gctf-2025-lost-transliteration` | Google CTF 2025 |
| 8103 | `gctf-2025-mythos-perl` | Google CTF 2025 |
| 8111 | `ductf-2024-co2` | DownUnderCTF 2024 |
| 8112 | `ductf-2024-sniffy` | DownUnderCTF 2024 |
| 8113 | `hkcert-2024-webpage-to-pdf-1` | HKCERT CTF 2024 |

After downloading the required public source archives (see below), build the
challenge images referenced by each task's `environment/docker-compose.yaml`,
then run oracle checks before model calibration.

Add new Harbor tasks under `harbor/tasks/` once the service has been validated
in isolation and documented in `REPORT.md`.

## Transcript viewer

For an interactive step-through of agent turns (plus the run summary from
`result.json`), start the local server and open the URL it prints:

```bash
python transcript-viewer/server.py
```

Defaults to http://127.0.0.1:8765/. Use **Harbor jobs** for
`jobs/<job>/<trial>/agent/trajectory.json`, or **Legacy runs** for
`runs/<bundle>/<run>/transcript.jsonl`. **Reload** re-reads files from disk.
Optional flags: `--port`, `--jobs-dir`, `--runs-dir`, `--repo-root`
(see `python transcript-viewer/server.py --help`).

## Public Source Archives

Raw public CTF archives are configured in
`sources/public_web_ctf_sources.json` and download into
`resources/ctf-archives/`. The current Web-5 Harbor tasks need Google CTF,
DownUnderCTF 2024, and HKCERT CTF sources:

```bash
python scripts/download_sources.py --source-id google-ctf
python scripts/download_sources.py --source-id downunderctf-2024
python scripts/download_sources.py --source-id hkcert-ctf
```

## Legacy manifest runner (fallback)

`bundles/*/manifest.json` is the older Cyber-Bench task format. The CLI can
still validate manifests, generate per-run Compose files, and drive the
in-process API runner or OpenCode backend. **Prefer Harbor for new task work.**

The container topology matches Harbor (`target` gateway + challenge services).
Differences: the agent service is named `attacker` (host `docker compose exec`),
scoring uses the `submit_flag` tool instead of `/app/flags.txt`, and artifacts
land under `runs/` instead of `jobs/`.

Activate the local environment first:

```bash
source .venv/bin/activate
```

General CLI checks:

```bash
python -m cyberbench.cli validate-config
python -m cyberbench.cli check-openrouter
python -m cyberbench.cli validate-bundle bundles/web-5/manifest.json
python -m cyberbench.cli prepare-run bundles/web-5/manifest.json
python -m cyberbench.cli run bundles/web-5/manifest.json --model openai/gpt-5.5 --level 4
python -m cyberbench.cli run-opencode bundles/web-5/manifest.json --model openai/gpt-5.5 --level 4
```

`run` requires Docker with the Compose plugin. It gives the model two tools:
shell execution inside the attacker container and structured flag submission.
The default attacker image is the same one Harbor's `main` container uses.

For OpenCode runs, install `opencode` separately (`npm i -g opencode-ai@latest`).
OpenCode uses `./bench_shell` and `./submit_flag` helpers in an isolated
workspace under `/tmp/cyberbench-opencode/`. See `docs/architecture.md` for
details.

Run artifacts live under `runs/<bundle_id>/<local_timestamp>_<model_slug>/`:

```bash
jq . runs/<bundle_id>/<run-folder>/result.json
tail -n 20 runs/<bundle_id>/<run-folder>/transcript.jsonl
```

Legacy manifests under `bundles/web-5/` and `bundles/individial_tasks/` mirror
the checked Harbor tasks and are kept for transcript viewer integration and
historical comparison against existing `runs/` artifacts.

## Assets

Raw public CTF downloads belong under ignored `resources/ctf-archives/`.
Committed files should be Harbor task directories under `harbor/tasks/`, runner
code, import scripts, and documentation. Legacy manifests under `bundles/` are
kept for the fallback runner only.
