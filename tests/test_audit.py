"""Audit: structural audit (orphans, broken links, …) + coordination-graph audit."""

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


# --- structural audit ---


def test_structural_audit_empty_wiki_reports_no_issues(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "no issues found" in out


def test_structural_audit_detects_orphan_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "lonely.md").write_text("# Lonely\n\nNo one links to me.\n")

    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "orphans" in out
    assert "lonely" in out or "lonely.md" in out


def test_structural_audit_detects_broken_link(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    src = wd / "source.md"
    src.write_text("# Source\n\nSee [[nonexistent-target]] for details.\n")

    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "broken links" in out
    assert "nonexistent-target" in out


def test_structural_audit_detects_unindexed_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "unindexed.md").write_text("# Unindexed\n\nContent.\n")
    (wiki / "index.md").write_text("# Wiki Index\n\n## Categories\n")

    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "unindexed" in out


def test_structural_audit_detects_empty_page(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "empty.md").write_text("---\ntitle: empty\n---\n")

    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "empty/trivial" in out


def test_structural_audit_detects_stale_inbox(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    stale = inbox / "stale.json"
    stale.write_text('{"id":"stale","title":"old","entity_type":"claim","content":"x"}')
    old_time = stale.stat().st_mtime - (8 * 86400)
    import os

    os.utime(stale, (old_time, old_time))

    rc, out = cli.main(["audit", "--structural"]), capsys.readouterr().out
    assert rc == 0
    assert "stale inbox" in out
    assert "stale.json" in out


def test_structural_audit_json_output(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    wd = _wiki_dir(wiki)
    (wd / "orphan.md").write_text("# Orphan\n\nContent.\n")

    rc, out = cli.main(["audit", "--structural", "--json"]), capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data["orphans"], list)
    assert isinstance(data["total_pages"], int)


def test_structural_audit_does_not_mutate_wiki(tmp_path, monkeypatch, capsys):
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

    cli.main(["audit", "--structural"])

    after_files = set(wiki.rglob("*"))
    assert after_files == before_files, "audit created or removed files"
    for p in after_files:
        assert p.stat().st_mtime == before_mtimes[p], f"audit modified {p}"


# --- coordination-graph audit ---


import os
import subprocess
from datetime import datetime, timezone

from haikei_wiki.audit import run_audit

_NOW = datetime(2026, 1, 20, tzinfo=timezone.utc)


def _git_repo(tmp: Path, name: str, files=None, branches=()):
    import os as _os

    root = tmp / name
    root.mkdir(parents=True)
    env = {
        **_os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init"], cwd=root, capture_output=True, env=env)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=root,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        capture_output=True,
        env=env,
    )
    if files:
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=root,
            capture_output=True,
            env=env,
            check=False,
        )
    for branch in branches:
        subprocess.run(
            ["git", "branch", branch], cwd=root, capture_output=True, env=env
        )
    return root


def _make_page(path: Path, title: str, body: str, status: str = "", **kw):
    lines = ["---", f"title: {title}", f"category: {kw.get('category', 'claim')}"]
    if status:
        lines.append(f"status: {status}")
    for k, v in kw.items():
        if k in ("category",):
            continue
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def test_run_audit_empty_wiki(tmp_path):
    wiki = tmp_path / "wik"
    wiki.mkdir()
    (wiki / "wiki").mkdir()
    report = run_audit(wiki, stale_days=7, extra_repo_dirs=[])
    assert report.pages_scanned == 0
    assert report.findings == []


def test_run_audit_does_not_touch_non_coordination(tmp_path):
    wiki = tmp_path / "wik"
    wiki.mkdir()
    wd = wiki / "wiki"
    wd.mkdir()
    (wd / "imported.md").write_text("---\ntitle: imported\n---\n\ncontent")
    (wd / "notes.md").write_text("---\ntitle: notes\n---\n\ncontent")
    report = run_audit(wiki, stale_days=7, extra_repo_dirs=[])
    assert report.pages_scanned == 0


def test_run_audit_no_findings_ok(tmp_path):
    wiki = tmp_path / "wik"
    wiki.mkdir()
    wd = wiki / "wiki"
    wd.mkdir()
    _make_page(wd / "claim" / "ok.md", "ok", "still valid", status="current")
    _make_page(
        wd / "decision" / "dec1.md",
        "dec1",
        "we decided to use X",
        category="decision",
    )
    report = run_audit(wiki, stale_days=7, extra_repo_dirs=[])
    assert report.findings == []


def test_run_audit_claims_older_than_stale_days(tmp_path):
    wiki = tmp_path / "wik"
    wiki.mkdir()
    wd = wiki / "wiki"
    wd.mkdir()
    p = wd / "claim" / "old.md"
    _make_page(p, "old claim", "The API contract is ...")
    created = _NOW.timestamp() - (14 * 86400)
    os.utime(p, (created, created))
    report = run_audit(wiki, stale_days=7, extra_repo_dirs=[])
    assert len(report.findings) >= 1
    assert any(f.check == "unresolved_claim" for f in report.findings)


def test_run_audit_recent_claims_not_flaggged(tmp_path):
    wiki = tmp_path / "wik"
    wiki.mkdir()
    wd = wiki / "wiki"
    wd.mkdir()
    p = wd / "claim" / "recent.md"
    _make_page(p, "recent", "just filed")
    now = datetime.now(timezone.utc).timestamp()
    os.utime(p, (now - 2, now - 2))
    report = run_audit(wiki, stale_days=7, extra_repo_dirs=[])
    unresolved = [f for f in report.findings if f.check == "unresolved_claim"]
    assert len(unresolved) == 0
