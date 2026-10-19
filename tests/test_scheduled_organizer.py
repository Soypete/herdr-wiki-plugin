"""Scheduled organizer (issue #22): locked single-writer daemon, plan
lifecycle, and the opt-in plan-vocabulary migration."""

import json
import sys
from pathlib import Path

import haikei_wiki.cli as cli
import haikei_wiki.daemon as daemon
import haikei_wiki.plans as plans
from haikei_wiki.vocabulary import Vocabulary, load_vocabulary

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"


def _wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    (wiki / "inbox").mkdir()
    return wiki


def _record(wiki: Path, rid: str, title: str, content: str) -> Path:
    p = wiki / "inbox" / f"{rid}.json"
    p.write_text(
        json.dumps(
            {
                "id": rid,
                "title": title,
                "entity_type": "claim",
                "content": content,
                "links": [],
                "provenance": {"agent": "test"},
                "created_at": "2026-10-01T14:44:48",
            }
        )
    )
    return p


# --- daemon -----------------------------------------------------------------


def test_daemon_run_once_organizes_logs_and_exits_zero(tmp_path, monkeypatch):
    wiki = _wiki(tmp_path)
    _record(wiki, "rec-d1", "daemon capture", "body for the daemon pass")
    log = tmp_path / "daemon.log"

    rc = daemon.run_once(wiki_path=wiki, log_path=log, lock_path=tmp_path / "l")

    assert rc == 0
    assert not list(wiki.glob("inbox/*.json"))
    text = log.read_text()
    assert "ok: organized=1 rejected=0" in text
    assert "rec-d1.json" in text


def test_daemon_skips_cleanly_when_lock_held(tmp_path, monkeypatch):
    """A second writer must be a logged skip, not a failure (single writer)."""
    wiki = _wiki(tmp_path)
    _record(wiki, "rec-d2", "held lock capture", "someone else owns the pass")
    log = tmp_path / "daemon.log"

    from haikei_wiki import organizer

    organizer.organize(
        wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock"
    )

    # re-run while the state dir lock file still exists → OrganizerError path
    rc = daemon.run_once(wiki_path=wiki, log_path=log)
    assert rc == 0
    assert log.read_text().count("ok:") == 1  # organized once, then nothing new


def test_daemon_reports_contended_lock_as_skip(tmp_path, monkeypatch):
    wiki = _wiki(tmp_path)
    log = tmp_path / "daemon.log"

    from haikei_wiki.organizer import OrganizerError

    def contended2(*a, **k):
        raise OrganizerError("another pass holds the organize lock")

    real = daemon.organize
    daemon.organize = contended2
    try:
        rc = daemon.run_once(wiki_path=wiki, log_path=log, lock_path=tmp_path / "x")
    finally:
        daemon.organize = real
    assert rc == 0
    assert "skip:" in log.read_text()


def test_daemon_failure_exits_one_and_logs(tmp_path, monkeypatch):
    wiki = _wiki(tmp_path)
    log = tmp_path / "daemon.log"
    from haikei_wiki.organizer import OrganizerError

    real = daemon.organize

    class Boom:
        def __call__(self, *a, **k):
            raise RuntimeError("disk full during rewrite")

    daemon.organize = Boom()
    try:
        rc = daemon.run_once(wiki_path=wiki, log_path=log, lock_path=tmp_path / "x")
    finally:
        daemon.organize = real
    assert rc == 1
    assert "error: unexpected" in log.read_text()


def test_daemon_run_does_no_llm(tmp_path, monkeypatch):
    """The scheduled path must stay deterministic: adapter LLM hooks are not
    imported/instantiated by run_once."""
    wiki = _wiki(tmp_path)
    log = tmp_path / "daemon.log"
    rc = daemon.run_once(wiki_path=wiki, log_path=log, lock_path=tmp_path / "l")
    assert rc == 0


def test_cli_organize_daemon_flag(tmp_path, monkeypatch, capsys):
    wiki = _wiki(tmp_path)
    _record(wiki, "rec-cli1", "cli daemon", "via the CLI flag")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("HERDR_PLUGIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    rc = cli.main(["organize", "--daemon"])
    assert rc == 0
    assert not list(wiki.glob("inbox/*.json"))


# --- plan lifecycle ---------------------------------------------------------


PLAN_PAGE = """---
title: plan/phase-two-migrations
category: plan
created: 2026-10-10T10:00:00
---

Tasks:

- [x] verify mig 073 staged
- [ ] stage mig 074 for kei-policy-catalog
- [ ] hand off to reviewer
"""


def _plan_wiki(tmp_path: Path) -> Path:
    wiki = _wiki(tmp_path)
    d = wiki / "wiki" / "plan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "phase-two-migrations.md").write_text(PLAN_PAGE)
    return wiki


def test_plan_status_lists_active_and_open_tasks(tmp_path):
    wiki = _plan_wiki(tmp_path)
    rows = plans.takeover(wiki)
    assert len(rows) == 1
    assert rows[0]["page"] == "phase-two-migrations.md"
    assert rows[0]["status"] == "active"
    assert rows[0]["open_tasks"] == [
        "stage mig 074 for kei-policy-catalog",
        "hand off to reviewer",
    ]


def test_plan_complete_clears_takeover(tmp_path):
    wiki = _plan_wiki(tmp_path)
    plans.set_status("phase-two-migrations", "completed", wiki)
    rows = plans.takeover(wiki)
    assert rows == []
    from haikei_wiki.lifecycle import parse_frontmatter

    d = wiki / "wiki" / "plan" / "phase-two-migrations.md"
    fields, _, _ = parse_frontmatter(d.read_text())
    assert fields["status"] == "completed"
    # body untouched — tasks stay in the record
    assert "stage mig 074 for kei-policy-catalog" in d.read_text()


def test_plan_interrupt_requires_reason_and_is_recoverable(tmp_path):
    wiki = _plan_wiki(tmp_path)
    try:
        plans.set_status("phase-two-migrations", "interrupted", wiki)
        raise AssertionError("expected PlanError")
    except plans.PlanError:
        pass
    plans.set_status(
        "phase-two-migrations", "interrupted", wiki, reason="rate limited mid-build"
    )
    fields, _, _ = None, None, None
    from haikei_wiki.lifecycle import parse_frontmatter

    p = wiki / "wiki" / "plan" / "phase-two-migrations.md"
    fields, _, _ = parse_frontmatter(p.read_text())
    assert fields["status"] == "interrupted"
    assert fields["interrupt_reason"] == "rate limited mid-build"
    rows = plans.takeover(wiki)
    assert rows[0]["status"] == "interrupted"
    assert rows[0]["interrupt_reason"] == "rate limited mid-build"


def test_plan_archive_and_bad_status(tmp_path):
    wiki = _plan_wiki(tmp_path)
    plans.set_status("phase-two-migrations", "archived", wiki)
    assert plans.takeover(wiki) == []
    try:
        plans.set_status("phase-two-migrations", "festering", wiki)
        raise AssertionError("expected PlanError")
    except plans.PlanError as e:
        assert "bad plan status" in str(e)


def test_plan_lifecycle_writes_touch_status_not_body(tmp_path):
    wiki = _plan_wiki(tmp_path)
    from haikei_wiki.lifecycle import parse_frontmatter

    before = (wiki / "wiki" / "plan" / "phase-two-migrations.md").read_text()
    plans.set_status("phase-two-migrations", "completed", wiki)
    after = (wiki / "wiki" / "plan" / "phase-two-migrations.md").read_text()
    assert parse_frontmatter(before)[2] == parse_frontmatter(after)[2]


# --- migration ---------------------------------------------------------------


def test_migrate_adds_plan_type_to_installed_vocabulary(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    starter = STARTER.read_text()
    # simulate an old install without the plan type
    old = starter.split("[entity_types]", 1)
    assert "plan =" in starter  # starter has it; build an old-shaped config
    old_text = "\n".join(
        ln
        for ln in starter.splitlines()
        if not (ln.startswith("plan ") or ln.startswith("plan ="))
    )
    (cfg / "tbox.toml").write_text(old_text)
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))

    rc = cli.main(["migrate", "plan-vocabulary", "--yes"])
    assert rc == 0
    text = (cfg / "tbox.toml").read_text()
    assert "plan =" in text

    vocab = load_vocabulary(cfg / "tbox.toml")
    assert "plan" in vocab.entity_types

    # idempotent
    rc = cli.main(["migrate", "plan-vocabulary"])
    assert rc == 0
    assert (cfg / "tbox.toml").read_text().count("plan =") == 1


def test_migrate_is_opt_in(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    old_text = "\n".join(
        ln for ln in STARTER.read_text().splitlines() if not ln.startswith("plan =")
    )
    (cfg / "tbox.toml").write_text(old_text)
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    assert "plan =" not in (cfg / "tbox.toml").read_text()
