"""Search surfaces pending inbox records alongside settled wiki pages.

Defect 1 fix: `wiki search` must find unorganized inbox captures so an agent
sees another agent's claim before editing shared files. Search is strictly
READ-ONLY on the inbox: the organizer remains the only writer to the graph.
"""

import json
from pathlib import Path

import haikei_wiki.cli as cli

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"


def _make_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    return wiki


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    wiki = _make_wiki(tmp_path)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return wiki


def _seed(wiki: Path, id: str, title: str, content: str) -> Path:
    inbox = wiki / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{id}.json"
    path.write_text(
        json.dumps(
            {
                "id": id,
                "title": title,
                "entity_type": "claim",
                "content": content,
                "links": [],
                "provenance": {"agent": "test"},
                "created_at": "2026-09-10T00:00:00",
            }
        )
    )
    return path


def _search(cli_args, capsys):
    rc = cli.main(cli_args)
    out = capsys.readouterr().out
    return rc, out


def test_inbox_record_found_by_title(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-title", "coord/claim-ws0-smoke", "some content body")

    rc, out = _search(["search", "claim-ws0-smoke"], capsys)

    assert rc == 0
    assert "inbox:" in out
    assert "coord/claim-ws0-smoke" in out


def test_inbox_record_found_by_content(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-content", "unrelated title", "flarpberry distinct token")

    rc, out = _search(["search", "flarpberry"], capsys)

    assert rc == 0
    assert "inbox:" in out


def test_inbox_results_marked_distinct_from_wiki_pages(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-a", "pending claim about index", "pending body")
    wiki_dir = wiki / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "settled.md").write_text("a settled page about index")

    rc, out = _search(["search", "index"], capsys)

    assert rc == 0
    # inbox records carry the inbox: path prefix and an 'inbox' source;
    # settled pages do not.
    lines = out.splitlines()
    inbox_lines = [l for l in lines if l.startswith("[") and "inbox:" in l]
    settled_lines = [l for l in lines if l.startswith("[") and "inbox:" not in l]
    assert inbox_lines, "expected an inbox-marked result"
    assert settled_lines, "expected a wiki page result"
    assert "inbox:" in inbox_lines[0]


def test_search_json_includes_inbox_with_stable_shape(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-json", "json shaped claim", "json shaped body")

    rc, out = _search(["search", "json shaped", "--json"], capsys)

    assert rc == 0
    data = json.loads(out)
    assert data["query"] == "json shaped"
    assert isinstance(data["results"], list)
    row = [r for r in data["results"] if r["path"].startswith("inbox:")]
    assert len(row) == 1
    assert row[0]["source"] == "inbox"
    assert set(row[0].keys()) == {"path", "source", "score", "snippet"}


def test_no_inbox_flag_excludes_pending_records(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-a", "pending only claim", "pending only body")

    rc, out = _search(["search", "pending only", "--no-inbox"], capsys)

    assert rc == 1
    assert "no results" in out
    assert "inbox:" not in out


def test_malformed_json_record_is_skipped_not_fatal(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-ok", "good record", "good record body")
    inbox = wiki / "inbox"
    (inbox / "rec-broken.json").write_text("{ not valid json")

    rc, out = _search(["search", "record"], capsys)

    assert rc == 0
    assert "inbox:" in out
    assert "good record" in out


def test_unreadable_file_is_skipped_not_fatal(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-ok", "good record", "good record body")
    inbox = wiki / "inbox"
    (inbox / "rec-unreadable.json").write_text("\x00\x01\x02")

    rc, out = _search(["search", "record"], capsys)

    assert rc == 0
    assert "inbox:" in out


def test_search_wiki_without_inbox_still_works(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    assert not (wiki / "inbox").exists()

    rc, out = _search(["search", "anything"], capsys)

    assert rc == 1  # no results anywhere, but no crash
    assert "no results" in out


def test_search_does_not_mutate_inbox(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _seed(wiki, "rec-a", "mutation probe", "probe body")
    _seed(wiki, "rec-b", "second record", "second body")
    inbox = wiki / "inbox"

    before = sorted(p.name for p in inbox.glob("*.json"))
    before_contents = {p.name: p.read_bytes() for p in sorted(inbox.glob("*.json"))}
    before_log = (wiki / "log.md").read_text()

    rc, out = _search(["search", "probe"], capsys)
    assert rc == 0
    # Search multiple times, text and json.
    _search(["search", "second", "--json"], capsys)

    after = sorted(p.name for p in inbox.glob("*.json"))
    after_contents = {p.name: p.read_bytes() for p in sorted(inbox.glob("*.json"))}
    assert after == before
    assert after_contents == before_contents
    assert (wiki / "log.md").read_text() == before_log
    # nothing moved into processed/rejected by a search
    assert not (inbox / "processed").exists()
    assert not (inbox / "rejected").exists()


def test_merged_results_sorted_by_score(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    # inbox record matching only in content (0.6)
    _seed(wiki, "rec-content", "unrelated", "blockchain mention in body")
    # wiki page matching in filename (0.9)
    wiki_dir = wiki / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "blockchain.md").write_text("a settled blockchain page")

    rc, out = _search(["search", "blockchain", "--json"], capsys)

    assert rc == 0
    data = json.loads(out)
    scores = [r["score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True), "results must sort by score"
    assert scores[0] == 0.9  # title/filename match ranks above content match
    sources = {r["source"] for r in data["results"]}
    assert "inbox" in sources and "blockchain.md" in sources
