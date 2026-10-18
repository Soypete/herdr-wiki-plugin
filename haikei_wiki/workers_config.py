"""Worker dispatch capacity config (issue #23).

A first-class configuration for the orchestrator's dispatch capacity:
which worker harnesses are installed and allowed, which models each may
run, and how many parallel workers the machine should carry. Read at plan
time by the orchestrator so dispatches are declared, not probed:

    # $HERDR_PLUGIN_CONFIG_DIR/worker-capacity.toml
    [parallel_capacity]
    max_workers = 4                # global cap; [repos."owner/name"] overrides

    [repos."HaikeiLabs/kei"]
    max_workers = 2

    [harnesses.codex]
    mode = "headless"
    command = ["codex", "exec", "--model", "{model}"]

    [harnesses.codex.models]
    default = "gpt-5-codex"
    large = "gpt-5-codex"          # optional per-task-type override
    quick = "gpt-5-mini"

    # opencode 2.0: the minimal TUI takes the model at launch
    # (`opencode mini -m provider/model`); mid-session switching is a
    # Ctrl+P UI action, so the worker brief names the model too:
    [harnesses.opencode]
    mode = "interactive"
    command = ["opencode", "mini", "--model", "{model}"]

Precedence for a model: per-task override > harness default > global
fallback (`[models].fallback`). Unknown harness or model names are errors
at plan time, not dispatch time. Absent config ⇒ capacity is unlimited
and the orchestrator keeps today's probe behavior (documented, no error).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_HARNESSES = ("codex", "claude", "opencode", "pi")


class WorkersConfigError(ValueError):
    pass


@dataclass
class HarnessConfig:
    name: str
    enabled: bool = True
    mode: str = "headless"  # "headless" | "interactive"
    command: list[str] = field(default_factory=list)  # may contain {model}
    models: dict[str, str] = field(default_factory=dict)  # task-type → model
    default_model: str = ""

    def model_for(self, task_type: str | None, fallback: str = "") -> str:
        if task_type and task_type in self.models:
            return self.models[task_type]
        return self.default_model or fallback

    def model_is_declared(self) -> bool:
        """True when the launch command sets the model itself.

        Headless dispatch (run/exec subcommands) carries {model} in the
        command. Interactive sessions declare the model only if their launch
        flag supports it (opencode 2.0's minimal TUI does: `opencode mini
        --model <provider/model>`); otherwise the model is advisory — the
        worker brief must say which model to switch to (Ctrl+P), unenforced.
        """
        return any("{model}" in part for part in self.command)

    def build_command(self, model: str, task_type: str | None = None,
                      fallback: str = "") -> list[str]:
        """Launch command with the assigned model substituted.

        Raises when a headless harness has no {model} placeholder: there is
        no way to hand the assigned model to the process, so dispatching
        would silently ignore the config's steering.
        """
        if self.mode == "headless" and self.command and not any(
            "{model}" in part for part in self.command
        ):
            raise WorkersConfigError(
                f"harness {self.name} is headless but its command has no "
                "{{model}} placeholder: the assigned model "
                f"'{self.model_for(task_type, fallback)}' would be silently "
                "ignored"
            )
        return [part.replace("{model}", model) for part in self.command]


@dataclass
class WorkersConfig:
    source: Path | None
    max_workers: int | None = None  # None = unlimited (config absent)
    repo_overrides: dict[str, int] = field(default_factory=dict)
    harnesses: dict[str, HarnessConfig] = field(default_factory=dict)
    fallback_model: str = ""

    def capacity(self, repo: str | None = None) -> int | None:
        """Effective max parallel workers for a repo (None = unlimited)."""
        if repo and repo in self.repo_overrides:
            return self.repo_overrides[repo]
        return self.max_workers

    def check_dispatch(self, active: int, repo: str | None = None) -> None:
        """Raise WorkersConfigError if one more dispatch would exceed cap."""
        cap = self.capacity(repo)
        if cap is not None and active + 1 > cap:
            raise WorkersConfigError(
                f"parallel capacity {cap} reached ({active} active workers); "
                "finish or stop one before dispatching another"
            )

    def harness_for(self, name: str) -> HarnessConfig:
        h = self.harnesses.get(name)
        if h is None:
            raise WorkersConfigError(
                f"harness {name!r} is not in the capacity config "
                f"(installed: {', '.join(self.harnesses) or 'none'})"
            )
        return h

    def assign(self, harness: str, task_type: str | None = None) -> tuple[str, str]:
        """(harness, model) for a task, from the declared config."""
        h = self.harness_for(harness)
        if not h.enabled:
            raise WorkersConfigError(f"harness {harness!r} is configured but disabled")
        return harness, h.model_for(task_type, self.fallback_model)


def config_path() -> Path:
    from .vocabulary import config_dir

    return config_dir() / "worker-capacity.toml"


_SHAPE = """\
# herdr wiki worker capacity config (issue #23)
#
# Read by the orchestrator at plan time. Absent file = unlimited capacity
# and today's probing behavior.

[parallel_capacity]
max_workers = 4                     # global cap; per-repo overrides below

[repos."owner/name"]
max_workers = 2                     # per-repo override (optional)

# Model precedence: per-task override > harness default > [models].fallback.
#
# mode = "headless": dispatch command may contain {model}; the config SETS
#   the model on launch (e.g. `opencode run --model <m>`, `codex exec --model`).
# mode = "interactive": TUI harness - model cannot come from the CLI
#   (opencode 2.0 switches models via the Ctrl+P UI), so the assigned model
#   is advisory: the worker brief must name it and the worker switches.

[harnesses.codex]
mode = "headless"
command = ["codex", "exec", "--model", "{model}"]

[harnesses.codex.models]
default = "gpt-5-codex"
quick = "gpt-5-mini"                # per-task-type override

[harnesses.claude]
mode = "headless"
command = ["claude", "-p", "--model", "{model}"]

[harnesses.claude.models]
default = "claude-sonnet-4-5"

[harnesses.opencode]
# opencode 2.0: `opencode mini -m provider/model` launches the minimal TUI
# with the model set; mid-session switching is a Ctrl+P UI action, so the
# worker brief names the model too. mode stays "interactive" because the
# session is a live TUI.
mode = "interactive"
command = ["opencode", "mini", "--model", "{model}"]

[harnesses.opencode.models]
default = "opencode/grok-code"

[harnesses.pi]
enabled = false

[models]
fallback = "claude-sonnet-4-5"
"""


def example_config_text() -> str:
    return _SHAPE


def write_example(path: Path | None = None) -> Path:
    """Write a commented example config (no-op if one already exists)."""
    p = Path(path) if path else config_path()
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_SHAPE)
    return p


def load_config(path: Path | None = None) -> WorkersConfig:
    """Load the capacity config. Missing file = absent config (no error)."""
    p = Path(path) if path else config_path()
    if not p.exists():
        return WorkersConfig(source=None)
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise WorkersConfigError(f"bad capacity config {p}: {e}") from e

    cap_tbl = data.get("parallel_capacity", {})
    max_workers = cap_tbl.get("max_workers")
    if max_workers is not None and (
        not isinstance(max_workers, int) or max_workers < 1
    ):
        raise WorkersConfigError("parallel_capacity.max_workers must be a positive int")

    overrides = {}
    for repo, tbl in (data.get("repos") or {}).items():
        mw = (tbl or {}).get("max_workers")
        if not isinstance(mw, int) or mw < 1:
            raise WorkersConfigError(f"repos.{repo}.max_workers must be a positive int")
        overrides[repo] = mw

    models_tbl = data.get("models") or {}
    fallback_model = str(models_tbl.get("fallback", ""))

    harnesses: dict[str, HarnessConfig] = {}
    for name, tbl in (data.get("harnesses") or {}).items():
        if name not in KNOWN_HARNESSES:
            raise WorkersConfigError(
                f"unknown harness {name!r} (allowed: {', '.join(KNOWN_HARNESSES)})"
            )
        tbl = tbl or {}
        models = tbl.get("models") or {}
        default_model = str(models.get("default", ""))
        mode = str(tbl.get("mode", "headless"))
        if mode not in ("headless", "interactive"):
            raise WorkersConfigError(
                f"harness {name}: mode must be headless or interactive, "
                f"got {mode!r}"
            )
        h = HarnessConfig(
            name=name,
            enabled=bool(tbl.get("enabled", True)),
            mode=mode,
            command=[str(c) for c in (tbl.get("command") or [])],
            models={k: str(v) for k, v in models.items() if k != "default"},
            default_model=default_model,
        )
        if h.enabled and not h.default_model:
            raise WorkersConfigError(
                f"harness {name} is enabled but has no models.default"
            )
        harnesses[name] = h

    return WorkersConfig(
        source=p,
        max_workers=max_workers,
        repo_overrides=overrides,
        harnesses=harnesses,
        fallback_model=fallback_model,
    )
