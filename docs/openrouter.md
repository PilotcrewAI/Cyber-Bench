# OpenRouter Configuration

Cyber-Bench uses OpenRouter as the only model backend for v1. Put the API key in
`.env`:

```env
OPENROUTER_API_KEY=...
```

Choose the model with `--model`, or set a default OpenRouter model id:

```env
CYBERBENCH_MODEL=anthropic/claude-sonnet-4.5
```

If `--model` and `CYBERBENCH_MODEL` are both unset, the runner uses the built-in
default `anthropic/claude-sonnet-4.5`. Passing `--model` always wins over the env
variable.

Useful checks:

```bash
python -m cyberbench.cli validate-config
python -m cyberbench.cli check-openrouter
python -m cyberbench.cli check-openrouter --model openai/gpt-5-codex
```
