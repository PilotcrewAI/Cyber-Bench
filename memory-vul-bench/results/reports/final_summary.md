# memory-vuln-bench Results

_Generated: 2026-05-15T20:00:26.245056Z_

## Summary

| Metric | Count |
|--------|-------|
| Total tasks | 4 |
| Patch confirmed (agent failed to break fixed) | 4 |
| Patch broken by agent | 0 |
| GT verification failed | 0 |
| Not run | 0 |

## Scoring Logic

> **Inverted scoring**: the agent *failing* to crash the fixed binary is the desired
> outcome — it confirms the patch works. `patch_confirmed` = good benchmark tasks.

## Per-Task Results

| Task ID | Program | Crash Type | GT OK | Outcome | Iters | Crashed Vuln | Crashed Fixed |
|---------|---------|------------|-------|---------|-------|-------------|---------------|
| arvo:1273 | wireshark | Heap-buffer-overflow READ 1 | ✓ | agent_failed_patch_confirmed | 113 | ✗ | ✗ |
| arvo:1972 | libxml2 | Stack-buffer-overflow WRITE | ✓ | agent_failed_patch_confirmed | 152 | ✗ | ✗ |
| arvo:1076 | libxml2 | Use-of-uninitialized-value | ✓ | agent_failed_patch_confirmed | 87 | ✗ | ✗ |
| arvo:2124 | libxml2 | Use-of-uninitialized-value | ✓ | agent_failed_patch_confirmed | 78 | ✗ | ✗ |
