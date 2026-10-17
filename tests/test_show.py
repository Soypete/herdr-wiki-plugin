"""`wiki show`: full page / inbox record retrieval through the CLI."""

import json
from pathlib import Path

import haikei_wiki.cli as cli

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def _isolate(tmp_path, monkeypatch) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return wiki


def _make_page(
    wiki: Path, title: str = "draft-adr", body: str = "Body of the draft"
) -> Path:
    page = wiki / "wiki" / "decision" / f"{title}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        f"---\ntitle: Draft ADR\ncategory: decision\ncreated: 2026-10-01T00:00:00\n---\n\n"
        f"{body}\nSee [[other-page]] for background.\n"
    )
    return page


def test_show_full_page_by_path(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _make_page(wiki)
    rc = cli.main(["show", "wiki/decision/draft-adr.md"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "title: Draft ADR" in out
    assert "Body of the draft" in out
    assert "[[other-page]]" in out


def test_show_accepts_shorthand_specs(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _make_page(wiki)
    for spec in ("decision/draft-adr", "draft-adr"):
        rc = cli.main(["show", spec])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Body of the draft" in out


def test_show_json_includes_content_and_links(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _make_page(wiki)
    rc = cli.main(["show", "decision/draft-adr", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["title"] == "Draft ADR"
    assert data["category"] == "decision"
    assert data["created"] == "2026-10-01T00:00:00"
    assert "Body of the draft" in data["content"]
    assert data["links"] == ["other-page"]


def test_show_inbox_record(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    record = {
        "id": "20261001T144448933485-abcd",
        "title": "handoff note",
        "entity_type": "handoff",
        "content": "full contract text",
        "links": [{"predicate": "relates_to", "target": "decision/api"}],
        "created_at": "2026-10-01T14:44:48",
    }
    (inbox / f"{record['id']}.json").write_text(json.dumps(record))
    rc = cli.main(["show", "inbox:20261001T144448933485-abcd"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "full contract text" in out

    rc = cli.main(["show", "inbox:20261001T144448933485-abcd", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["title"] == "handoff note"
    assert data["links"] == ["relates_to:decision/api"]


def test_show_missing_page_errors(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc = cli.main(["show", "decision/nope"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no such page" in err
