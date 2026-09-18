"""Cleanup: safe, exact-selection delete of pages and inbox records."""

import json
from pathlib import Path

import haikei_wiki.cli as cli

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def _make_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    return wiki


def _isolate(tmp_path, monkeypatch) -> Path:
    wiki = _make_wiki(tmp_path)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return wiki


def _wiki_dir(wiki: Path) -> Path:
    d = wiki / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- delete page ---


def test_delete_page_by_exact_path(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wiki / "index.md").write_text(
        "# Wiki Index\n\n## Categories\n- [[wiki/target-page|Target]]\n"
    )
    target = wd / "target-page.md"
    target.write_text("---\ntitle: Target\n---\n\nContent.\n")

    rc, out = (
        cli.main(["delete", "page", "wiki/target-page.md"]),
        capsys.readouterr().out,
    )
    assert rc == 0
    assert "deleted page" in out

    assert not target.exists()
    idx = (wiki / "index.md").read_text()
    assert "target-page" not in idx
    log = (wiki / "log.md").read_text()
    assert "delete page" in log


def test_delete_page_nonexistent_returns_error(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc = cli.main(["delete", "page", "nonexistent.md"])
    _, err = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in err


def test_delete_inbox_by_exact_id(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    record = {
        "id": "rec-42",
        "title": "test record",
        "entity_type": "claim",
        "content": "test content",
        "links": [],
        "provenance": {"agent": "test"},
        "created_at": "2026-09-17T00:00:00",
    }
    (inbox / "rec-42.json").write_text(json.dumps(record))

    rc, out = cli.main(["delete", "inbox", "rec-42"]), capsys.readouterr().out
    assert rc == 0
    assert "deleted inbox record" in out

    assert not (inbox / "rec-42.json").exists()
    assert (inbox / "deleted" / "rec-42.json").exists()
    log = (wiki / "log.md").read_text()
    assert "delete inbox" in log


def test_delete_inbox_nonexistent_returns_error(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc = cli.main(["delete", "inbox", "no-such-id"])
    _, err = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in err


def test_delete_inbox_non_exact_spec_returns_error(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    record = {
        "id": "rec-99",
        "title": "exact match only",
        "entity_type": "claim",
        "content": "content",
        "links": [],
        "provenance": {"agent": "test"},
        "created_at": "2026-09-17T00:00:00",
    }
    (inbox / "rec-99.json").write_text(json.dumps(record))
    (inbox / "rec-99-extra.json").write_text(json.dumps(record))

    rc, out = cli.main(["delete", "inbox", "rec-99"]), capsys.readouterr().out
    assert rc == 0, f"exact match should work: {out}"

    rc2 = cli.main(["delete", "inbox", "rec-"])
    out2, err2 = capsys.readouterr()
    assert rc2 == 1
    all_text = out2 + err2
    assert "ERROR" in all_text
    assert "not exact" in all_text


def test_delete_logs_to_log_md(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    target = wd / "loggable.md"
    target.write_text("---\ntitle: Loggable\n---\n\nContent.\n")

    before = (wiki / "log.md").read_text()
    cli.main(["delete", "page", "wiki/loggable.md"])
    after = (wiki / "log.md").read_text()

    assert len(after) > len(before)
    assert "delete page" in after
    assert "Loggable" in after
