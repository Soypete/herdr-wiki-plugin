"""Audit: read-only structural scan for orphans, broken links, etc."""

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


def test_audit_empty_wiki_reports_no_issues(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "no issues found" in out


def test_audit_detects_orphan_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "lonely.md").write_text("# Lonely\n\nNo one links to me.\n")

    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "orphans" in out
    assert "lonely" in out or "lonely.md" in out


def test_audit_detects_broken_link(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    src = wd / "source.md"
    src.write_text("# Source\n\nSee [[nonexistent-target]] for details.\n")

    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "broken links" in out
    assert "nonexistent-target" in out


def test_audit_detects_unindexed_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "unindexed.md").write_text("# Unindexed\n\nContent.\n")
    (wiki / "index.md").write_text("# Wiki Index\n\n## Categories\n")

    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "unindexed" in out


def test_audit_detects_empty_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "empty.md").write_text("---\ntitle: empty\n---\n")

    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "empty/trivial" in out


def test_audit_detects_stale_inbox(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    stale = inbox / "stale.json"
    stale.write_text('{"id":"stale","title":"old","entity_type":"claim","content":"x"}')
    # Set mtime to 8 days ago
    old_time = stale.stat().st_mtime - (8 * 86400)
    import os

    os.utime(stale, (old_time, old_time))

    rc, out = cli.main(["audit"]), capsys.readouterr().out
    assert rc == 0
    assert "stale inbox" in out
    assert "stale.json" in out


def test_audit_json_output(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "orphan.md").write_text("# Orphan\n\nContent.\n")

    rc, out = cli.main(["audit", "--json"]), capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data["orphans"], list)
    assert isinstance(data["total_pages"], int)


def test_audit_does_not_mutate_wiki(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "page.md").write_text("# Page\n\nContent.\n")
    inbox = wiki / "inbox"
    inbox.mkdir()
    (inbox / "rec.json").write_text(
        '{"id":"rec","title":"t","entity_type":"claim","content":"c"}'
    )

    before_files = set(wiki.rglob("*"))
    before_mtimes = {p: p.stat().st_mtime for p in before_files}

    cli.main(["audit"])

    after_files = set(wiki.rglob("*"))
    assert after_files == before_files, "audit created or removed files"
    for p in after_files:
        assert p.stat().st_mtime == before_mtimes[p], f"audit modified {p}"
