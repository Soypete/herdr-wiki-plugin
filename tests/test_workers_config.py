"""Worker dispatch capacity config (issue #23): schema, precedence,
capacity enforcement, opencode model handling, and absence fallback."""

import tomllib
from pathlib import Path

import pytest

import haikei_wiki.cli as cli
import haikei_wiki.workers_config as wc
from haikei_wiki.workers_config import (
    HarnessConfig,
    WorkersConfig,
    WorkersConfigError,
    load_config,
)

ROOT = Path(__file__).resolve().parent.parent


def _cfg(tmp_path: Path, text: str | None = None) -> Path:
    p = tmp_path / "worker-capacity.toml"
    p.write_text(text if text is not None else wc.example_config_text())
    return p


# --- absence fallback -------------------------------------------------------


def test_absent_config_is_unlimited_and_no_error(tmp_path):
    c = load_config(tmp_path / "does-not-exist.toml")
    assert c.source is None
    assert c.capacity("any/repo") is None
    c.check_dispatch(active=99)  # no cap → never raises
    with pytest.raises(WorkersConfigError):
        c.harness_for("opencode")  # but steering requires a declared harness


def test_absent_config_matches_current_behavior_documented(tmp_path):
    """The fallback must be the historical probing behavior: no default
    harnesses, no fake limits — a plan proceeds and probes as before."""
    c = WorkersConfig(source=None)
    assert c.capacity(None) is None
    assert c.harnesses == {}


# --- schema + capacity ------------------------------------------------------


def test_example_config_loads_with_capacity_and_override(tmp_path):
    c = load_config(_cfg(tmp_path))
    assert c.max_workers == 4
    assert c.capacity("owner/name") == 2
    assert c.capacity("other/repo") == 4


def test_check_dispatch_enforces_capacity(tmp_path):
    c = load_config(_cfg(tmp_path))
    with pytest.raises(WorkersConfigError) as e:
        c.check_dispatch(active=2, repo="owner/name")
    assert "parallel capacity 2 reached" in str(e.value)
    c.check_dispatch(active=2, repo="other/repo")  # global cap 4, fine
    c.check_dispatch(active=3, repo="other/repo")  # last slot
    with pytest.raises(WorkersConfigError):
        c.check_dispatch(active=4, repo="other/repo")  # at global cap


def test_bad_schema_is_a_plan_time_error(tmp_path):
    text = wc.example_config_text().replace("max_workers = 4", "max_workers = 0", 1)
    try:
        load_config(_cfg(tmp_path, text))
        raise AssertionError("expected WorkersConfigError")
    except WorkersConfigError as e:
        assert "positive int" in str(e)


def test_unknown_harness_name_rejected(tmp_path):
    text = wc.example_config_text() + '\n[harnesses.gemini]\ncommand = ["gemini"]\n'
    with pytest.raises(WorkersConfigError) as e:
        load_config(_cfg(tmp_path, text))
    assert "unknown harness 'gemini'" in str(e.value)


def test_enabled_harness_requires_default_model(tmp_path):
    text = wc.example_config_text().replace(
        "[harnesses.pi]\nenabled = false",
        "[harnesses.pi]\nenabled = true",
    )
    try:
        load_config(_cfg(tmp_path, text))
        raise AssertionError("expected WorkersConfigError")
    except WorkersConfigError as e:
        assert "models.default" in str(e)


def test_disabled_harness_may_omit_model(tmp_path):
    c = load_config(_cfg(tmp_path))
    assert c.harness_for("pi").enabled is False  # example ships pi disabled


# --- model steering precedence ---------------------------------------------


def test_model_precedence_task_over_default_over_fallback(tmp_path):
    c = load_config(_cfg(tmp_path))
    fallback = c.fallback_model
    # per-task override
    assert c.assign("codex", "quick")[1] == "gpt-5-mini"
    # harness default
    assert c.assign("codex", "large")[1] == "gpt-5-codex"
    # ... and default when the task type is unknown to the harness
    assert c.assign("claude", "unknown-type")[1] == "claude-sonnet-4-5"


def test_assign_refuses_undeclared_harness(tmp_path):
    c = load_config(_cfg(tmp_path))
    with pytest.raises(WorkersConfigError):
        c.assign("gemini")


def test_assign_refuses_disabled_harness(tmp_path):
    c = load_config(_cfg(tmp_path))
    text = wc.example_config_text().replace(
        "[harnesses.pi]\nenabled = false",
        '[harnesses.pi]\nenabled = true\nmodels.default = "pi/alpha"',
    )
    c2 = load_config(_cfg(tmp_path, text))
    assert c2.assign("pi", None)


# --- opencode mini / model declaration -------------------------------------


def test_opencode_mini_declares_model_at_launch(tmp_path):
    """opencode 2.0: `opencode mini --model <provider/model>` sets the model
    at launch; mid-session switching is the Ctrl+P UI, so the brief names
    the model too."""
    c = load_config(_cfg(tmp_path))
    harness, model = c.assign("opencode", "quick")  # task-type override
    assert model == "opencode/grok-code"
    cmd = c.harness_for("opencode").build_command(model, "quick")
    assert cmd[:2] == ["opencode", "mini"]
    assert cmd[-2:] == ["--model", model]


def test_interactive_without_model_flag_is_advisory(tmp_path):
    h = HarnessConfig(name="opencode", mode="interactive", command=["opencode"])
    assert h.model_is_declared() is False


def test_headless_without_model_placeholder_raises(tmp_path):
    """Dispatch would silently ignore the assigned model — refuse it."""
    h = HarnessConfig(name="codex", mode="headless", command=["codex", "exec"])
    with pytest.raises(WorkersConfigError) as e:
        h.build_command("gpt-5-codex")
    assert "silently" in str(e.value)


def test_placeholder_substitution_tolerates_repeats(tmp_path):
    h = HarnessConfig(
        name="opencode",
        mode="interactive",
        command=[
            "opencode",
            "mini",
            "--model",
            "{model}",
            "--prompt",
            "{model}-runner",
        ],
    )
    assert h.build_command("m/x")[-4:] == ["--model", "m/x", "--prompt", "m/x-runner"]


# --- example + migration ----------------------------------------------------


def test_example_file_is_valid_toml_roundtrip(tmp_path):
    raw = wc.example_config_text()
    data = tomllib.loads(raw)
    assert set(data["harnesses"]) <= set(wc.KNOWN_HARNESSES)
    assert raw.startswith("# herdr wiki worker capacity config")


def test_write_example_idempotent(tmp_path):
    p = tmp_path / "worker-capacity.toml"
    a = wc.write_example(p)
    before = p.read_text()
    b = wc.write_example(p)
    assert a == b == p
    assert p.read_text() == before


def test_cli_migrate_writes_capacity_config(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(
        (ROOT / "haikei_wiki" / "starter_tbox.toml").read_text()
    )
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))

    rc = cli.main(["migrate", "worker-capacity"])
    assert rc == 0
    written = cfg / "worker-capacity.toml"
    assert written.exists()
    data = tomllib.loads(written.read_text())
    assert "parallel_capacity" in data

    rc, out = cli.main(["migrate", "worker-capacity"]), capsys.readouterr()
    assert rc == 0
    assert "already present" in out.out

    rc = cli.main(["migrate", "no-such-migration"])
    assert rc == 2
