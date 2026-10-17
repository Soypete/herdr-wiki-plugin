"""Hybrid search index (issue #12).

- lexical FTS5 (BM25) over pages + pending inbox records, kept fresh by the
  capture/organize/delete lifecycle (incremental, no rebuild per query)
- hybrid default: RRF fusion, degrades to lexical when no embedding provider
  is available (offline-first)
- CLI: --mode lexical|semantic|hybrid, --explain, and --type/--since/--repo
  filters, --json with score breakdowns
"""

import json
from pathlib import Path

import haikei_wiki.cli as cli

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("HERDR_PLUGIN_STATE_DIR", str(tmp_path / "state"))
    # offline default: no embedding provider configured
    monkeypatch.delenv("WIKI_EMBED_MODEL", raising=False)
    monkeypatch.delenv("WIKI_EMBED_URL", raising=False)
    return wiki


def _run(args: list, capsys) -> tuple[int, str]:
    """Run one CLI command; each run's stdout/stderr is drained in turn."""
    rc = cli.main(args)
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    return rc, out + ("" if not err else "")


def _capture(title: str, ctype: str, content: str, capsys) -> dict:
    rc, _ = _run(
        ["capture", "--title", title, "--type", ctype, "--content", content], capsys
    )
    assert rc == 0, "capture must succeed"
    from haikei_wiki.capture import wiki_root

    records = sorted((wiki_root() / "inbox").glob("*.json"))
    assert records
    return json.loads(records[-1].read_text())


def _organize(capsys) -> None:
    rc, _ = _run(["organize"], capsys)
    assert rc == 0


def _search(query: str, capsys, *extra: str):
    rc, out = _run(["search", query, *extra], capsys)
    return rc, json.loads(out)


def test_capture_is_searchable_immediately(tmp_path, monkeypatch, capsys):
    tmp_path = tmp_path  # noqa: F841
    _isolate(tmp_path, monkeypatch)
    rec = _capture(
        "tf launch template claim", "claim", "EC2 CreateLaunchTemplate", capsys
    )
    _, data = _search("launch template", capsys, "--json")
    assert any(r["path"] == f"inbox:{rec['id']}" for r in data["results"])


def test_organize_file_to_page(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _capture("docker ci runner", "blocker", "docker-ci node group missing", capsys)
    _organize(capsys)
    _, data = _search("docker-ci node group", capsys, "--json")
    paths = [r["path"] for r in data["results"]]
    assert paths and not any(p.startswith("inbox:") for p in paths)
    assert any("docker" in p for p in paths)


def test_deleted_page_leaves_the_index(tmp_path, monkeypatch, capsys):
    from haikei_wiki.capture import wiki_root

    _isolate(tmp_path, monkeypatch)
    _capture("orphan claim", "claim", "uniquetoken987 in body", capsys)
    _organize(capsys)
    page = next((wiki_root() / "wiki").rglob("orphan-claim.md"))
    rc, _ = _run(["delete", "page", str(page)], capsys)
    assert rc == 0
    rc, data = _search("uniquetoken987", capsys, "--json")
    assert data["results"] == [], "deleted page must not surface in search"


def test_mode_and_explain_effects(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _capture("hybrid mode probe", "decision", "hybridmode token body", capsys)
    rc, data = _search("hybrid", capsys, "--mode", "lexical", "--explain", "--json")
    assert rc == 0
    assert data["search"]["mode"] == "lexical"
    for r in data["results"]:
        assert "scores" in r and "lexical" in r["scores"]


def test_semantic_degrades_offline(tmp_path, monkeypatch, capsys):
    """No embedding provider: hybrid still returns lexical results and the
    JSON meta marks semantics unavailable instead of erroring."""
    _isolate(tmp_path, monkeypatch)
    _capture("offline degrade", "claim", "degradetoken body", capsys)
    rc, data = _search("degradetoken", capsys, "--mode", "hybrid", "--json")
    assert rc == 0
    assert data["results"]
    assert data["search"].get("semantic_available") is False
    assert data["search"]["mode"] == "hybrid"


def test_unreachable_embedding_provider_still_searches(tmp_path, monkeypatch, capsys):
    """WIKI_EMBED_MODEL set but nothing listening: lexical fallback, no crash."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("WIKI_EMBED_MODEL", "test-embedder")
    monkeypatch.setenv("WIKI_EMBED_URL", "http://127.0.0.1:9")
    _capture("dead endpoint", "claim", "deadendpoint token", capsys)
    rc, data = _search("deadendpoint", capsys, "--mode", "hybrid", "--json")
    assert rc == 0
    assert data["results"], "must return lexical results despite embedder failure"


def test_filters_type_and_repo(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _capture("recent claim", "claim", "kernelfilter inside repo-x work", capsys)
    _capture("recent decision", "decision", "kernelfilter in repo-y", capsys)

    rc, data = _search("kernelfilter", capsys, "--type", "decision", "--json")
    assert rc == 0
    titles = json.dumps(data["results"])
    assert "recent claim" not in titles
    assert "recent decision" in titles

    rc, data = _search("kernelfilter", capsys, "--repo", "repo-y", "--json")
    assert rc == 0
    snippets = [r["snippet"] for r in data["results"]]
    assert snippets and all("repo-y" in s for s in snippets), snippets


def test_since_window_filters_old_records(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _capture("fresh record", "claim", "sincewindow body", capsys)
    from haikei_wiki.capture import wiki_root
    from datetime import datetime, timedelta, timezone

    rec_path = next((wiki_root() / "inbox").glob("*.json"))
    rec = json.loads(rec_path.read_text())
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rec["created_at"] = old
    rec_path.write_text(json.dumps(rec))

    rc, data = _search("sincewindow", capsys, "--since", "24h", "--json")
    assert data["results"] == [], "an old record must be excluded by the 24h window"
    rc, _ = _search("sincewindow", capsys, "--since", "60d", "--json")
    assert rc == 0


def test_fts5_index_lives_under_wiki_dot_index(tmp_path, monkeypatch, capsys):
    from haikei_wiki.search_index import SearchIndex

    wiki = _isolate(tmp_path, monkeypatch)
    _capture("index location", "claim", "loc body", capsys)
    index = SearchIndex(wiki)
    assert index.fts_ok is True
    assert index.doc_count() == 1
