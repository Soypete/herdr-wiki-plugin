# Worker dispatch capacity config (`worker-capacity.toml`)

The orchestrator skill used to discover dispatch capacity by trial-and-error:
a `herdr agent` probe per harness kind, corrected by the operator via chat.
This page documents the declared capacity config instead (issue #23).

## Location

`$HERDR_PLUGIN_CONFIG_DIR/worker-capacity.toml`
(`haikei_wiki` resolves the same config dir as the capture vocabulary; the
orchestrator reads it at **plan time**, before any dispatch). A commented
example lives at
[`worker-capacity.toml.example`](https://github.com/Soypete/herdr-wiki-plugin/blob/main/docs/worker-capacity.toml.example).

## Schema

```toml
[parallel_capacity]
max_workers = 4                     # global cap on simultaneous workers

[repos."owner/name"]                # optional per-repo override
max_workers = 2

[harnesses.codex]                   # one table per installed harness
mode = "headless"
command = ["codex", "exec", "--model", "{model}"]

[harnesses.codex.models]
default = "gpt-5-codex"
quick = "gpt-5-mini"                # optional per-task-type override

[models]
fallback = "claude-sonnet-4-5"      # used when a harness has no default
```

Allowed harnesses: `codex`, `claude`, `opencode`, `pi`. Unknown names are
rejected at load (plan-time error, not dispatch-time surprise).

## Model precedence

**per-task override > harness default > `[models].fallback`.**

```toml
[harnesses.opencode.models]
default = "opencode/grok-code"
quick = "opencode/grok-code"        # cheap tasks use the small model
```

## Headless vs interactive (model setting)

Dispatch modes differ in who sets the model:

- **`mode = "headless"`** — the launch command runs and exits; the model is
  declared. The command template must contain a `{model}` placeholder:
  - `opencode run --model "{model}"` (opencode 2.0: run is the only place a
    model can be handed to the CLI — in the interactive TUI, switching models
    is a Ctrl+P UI action, not a flag)
  - `codex exec --model "{model}"`
  - `opencode mini --model "{model}"` (the minimal TUI; see interactive above)
- **`mode = "interactive"`** — a live TUI session. Whether the config can
  set the model depends on the launch command:
  - opencode 2.0's minimal TUI accepts a model at launch:
    `opencode mini --model "{model}"` — declared.
  - anything without a model launch flag (model switching is a Ctrl+P UI
    action, not a CLI flag) is **advisory**: the worker brief must name it
    ("running model X; the session is not on it → switch with Ctrl+P") and
    it is not enforced.

`build_command(model)` raises if a headless harness has no `{model}`
placeholder — otherwise the assigned model would be silently ignored.

## Capacity enforcement

- `[parallel_capacity].max_workers` caps simultaneously active workers;
  `[repos."owner/name"].max_workers` narrows it for one repo.
- The orchestrator tracks `active + 1 > cap` **before** dispatching and
  refuses with the reason (finish or stop a worker first) instead of
  thrashing panes.
- Per-repo override wins over the global value.

## Absence = today's behavior

A missing `worker-capacity.toml` is not an error: capacity is unlimited and
the orchestrator keeps its current probe-and-adjust behavior. The doc string
on `haikei_wiki.workers_config.load_config` shows the exact fallback. An
unparseable file or a positive-int violation (`max_workers = 0`) is an error
at plan time — never a silent wrap-around.

## Setup

```bash
haikei-wiki migrate worker-capacity   # writes the commented example, no-op if present
```

…then edit `$HERDR_PLUGIN_CONFIG_DIR/worker-capacity.toml` to match the
machine: which harnesses are installed, their headless commands, and the
parallelism you actually want. Linked from
[`skills/README.md`](../skills/README.md) and
[the whitepaper](agent-swarm-coordination-whitepaper.md).
