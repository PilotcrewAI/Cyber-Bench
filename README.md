# Cyber-Bench


CyberExplorer-style environment: fixed curated bundles,
multiple exposed web services, scored CTF targets mixed with benign decoys, and
LLM agents through OpenRouter under cost budgets.

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

## Transcript viewer

For an interactive step-through of agent turns (plus the run summary from
`result.json`), start the small local server and open the URL it prints:

```bash
python transcript-viewer/server.py
```

Defaults to http://127.0.0.1:8765/ and reads under `runs/`. Choose bundle and run
from the dropdowns; **Reload** re-reads files from disk. Optional flags:
`--port`, `--runs-dir`, `--repo-root` (see `python transcript-viewer/server.py --help`).

## Public Source Archives

Raw public CTF archives are configured in
`sources/public_web_ctf_sources.json` and download into
`resources/ctf-archives/`:

```bash
python scripts/download_sources.py --source-id google-ctf
python scripts/scan_ctf_services.py --json
```

The scanner only finds candidate Docker-backed web services. A task still needs
manual curation before it enters a scored bundle: confirm license/provenance,
deduplicate against CyberExplorer's task set, normalize the flag where feasible,
and add the service to a bundle manifest.

## Curated Bundle

`bundles/google-web-10/manifest.json` is the first fixed real-web bundle. It
contains exactly 10 scored Google CTF web services and 3 benign web decoys.
It builds local images from the public Google CTF source archive because the
upstream prebuilt Google Artifact Registry images are permission-gated. Download
the source archive before validating, preparing, or running it:

```bash
python scripts/download_sources.py --source-id google-ctf
python -m cyberbench.cli validate-bundle bundles/google-web-10/manifest.json --strict
COMPOSE=$(python -m cyberbench.cli prepare-run bundles/google-web-10/manifest.json)
docker compose -f "$COMPOSE" build
```

`prepare-run` prints the path to the generated `compose.yml` under
`runs/<bundle_id>/<local_timestamp>_prepare/` (same local `YYYYMMDD_HHMMSS` as `run`).

The original upstream image references are still kept in the manifest `source`
metadata for provenance.

Run the curated bundle (each invocation creates a new run folder under `runs/<bundle_id>/`):

```bash
python -m cyberbench.cli run bundles/google-web-10/manifest.json \
  --model anthropic/claude-haiku-4.5

python -m cyberbench.cli run bundles/google-web-10/manifest.json \
  --model openai/gpt-5.4-nano
```

## Assets

Raw public CTF downloads belong under ignored `resources/ctf-archives/`.
Committed files should be normalized manifests, import scripts, runner code, and
documentation only.
