# Cyber-Bench


CyberExplorer-style environment: fixed curated bundles,
multiple exposed web services, scored CTF targets mixed with benign decoys, and
LLM agents through OpenRouter under wall-clock and model budgets.

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

Run artifacts live under `runs/<bundle_id>/<local_timestamp>_<model_slug>/`. The
timestamp is the machine’s **local** wall clock (`YYYYMMDD_HHMMSS`). OpenRouter
`/` and `:` in the model id become `-` in the inner folder name. Example:
`runs/smoke-web/20260511_143052_anthropic-claude-haiku-4.5/`.

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

Do not run costlier models until the cheap-model artifacts have been inspected.

## Assets

Raw public CTF downloads belong under ignored `resources/ctf-archives/`.
Committed files should be normalized manifests, import scripts, runner code, and
documentation only.
