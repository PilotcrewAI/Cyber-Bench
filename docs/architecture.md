# Runtime architecture

This document describes how one `cyberbench.cli run` wires Docker, the LLM
agent, and bundle targets together.

## Components

- **Host process** — `python -m cyberbench.cli run` loads the manifest, writes
  `compose.yml` under the run directory, runs `docker compose up`, then drives
  `AgentRunner` until a terminal status (solved, timeout, budget, or give up).
- **Attacker container** (`attacker`) — Long-lived shell environment. The model’s
  `shell` tool is implemented as `docker compose exec` into this service. Recon
  and exploitation commands run here (e.g. `curl`, `nmap`). See
  `cyberbench/runtime/docker.py` and `cyberbench/runtime/attacker/`.
- **Gateway container** (`target`) — Runs `cyberbench/runtime/gateway.py`. It
  listens on the manifest’s stable **target ports** (e.g. 8101, 8102, …) and
  TCP-forwards each to the correct challenge container and its **container
  port** (e.g. 1337). The map comes from `CYBERBENCH_GATEWAY_MAP`.
- **Challenge and decoy containers** — One Compose service per `manifest.services`
  entry. Each bundles a distinct app/stack (different images, env, sometimes
  `privileged`). They only need to accept traffic from the internal Docker
  network.

The model never talks to Docker directly. It receives tool results over the API;
only **shell** and **submit_flag** are exposed (`cyberbench/runner.py`).

## One session, many targets

A single agent run loops until all **scored** services are flagged or budgets
expire. Containers for every service start **together** under one Compose
project shared network (`bench`). The attacker reaches challenges by host
name **`target`** and the manifest-listed ports—not by connecting to each
service’s Compose hostname on its raw container port unless you do that manually
inside the attacker.

## Internal network versus your laptop

All of the above listening happens on Docker’s **`bench`** network. The compose
generator does **not** add `ports:` mappings for those target ports onto the
host, so **`curl http://127.0.0.1:8101` on the host does not reach the benchmark
by default**. To reproduce the agent’s view from the host you would add explicit
`ports` in the generated file, or run commands inside the `attacker` container
(e.g. `curl http://target:8101`).

## Diagram: services and traffic

```mermaid
flowchart TB
    subgraph Host["Host machine"]
        subgraph Docker["Docker"]
            subgraph Bench["Docker network: bench"]
                atk["attacker (model shell exec)"]
                gw["target (gateway.py)"]
                s1["Challenge container 1"]
                s2["Challenge container 2"]
                sn["More challenges + decoys"]
                tip["Compose does not publish 8101+ to localhost by default."]
            end
        end
    end

    atk -->|"HTTP(S) to target:8101 etc."| gw
    gw --> s1
    gw --> s2
    gw --> sn
    atk --- tip
```

### One shell request path

```mermaid
sequenceDiagram
    participant M as "Model API"
    participant R as AgentRunner
    participant A as "attacker container"
    participant T as "target gateway"
    participant S as "challenge container"

    M->>R: tool_call shell
    R->>A: docker compose exec attacker sh -lc "..."

    Note over A,S: Typical probe
    A->>T: e.g. curl http://target:8101
    T->>S: forwarded to backend host/port from gateway map
    S-->>T: HTTP response
    T-->>A: response
    A-->>R: stdout / stderr
    R-->>M: tool result JSON

    M->>R: tool_call submit_flag
    R-->>M: scoring vs manifest only
```

## Key files

| Area | Location |
| -------- | ------- |
| Compose generation | `cyberbench/runtime/docker.py` |
| TCP forwarding | `cyberbench/runtime/gateway.py` |
| Agent loop & tools | `cyberbench/runner.py` |
| CLI orchestration | `cyberbench/cli.py` |
| Bundle schema & ports | `cyberbench/manifest.py`, bundle `manifest.json` |
