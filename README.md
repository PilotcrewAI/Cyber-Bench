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
submission.

Use OpenRouter model IDs directly:

```bash
python -m cyberbench.cli run bundles/smoke-web/manifest.json --model anthropic/claude-haiku-4.5
python -m cyberbench.cli run bundles/smoke-web/manifest.json --model openai/gpt-5.4-nano
```

## Public Source Archives

Raw public CTF archives are configured in
`sources/public_web_ctf_sources.json` and download into ignored
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
Download the source archive before validating or preparing it:

```bash
python scripts/download_sources.py --source-id google-ctf
python -m cyberbench.cli validate-bundle bundles/google-web-10/manifest.json --strict
python -m cyberbench.cli prepare-run bundles/google-web-10/manifest.json --run-dir runs/prepare-google-web-10
docker compose -f runs/prepare-google-web-10/compose.yml build
```

The bundle builds services from the public challenge Dockerfiles because the
upstream prebuilt Artifact Registry images are not anonymously pullable.

## Assets

Raw public CTF downloads belong under ignored `resources/ctf-archives/`.
Committed files should be normalized manifests, import scripts, runner code, and
documentation only.
