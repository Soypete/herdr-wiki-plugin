"""Organizer: single-writer reconciliation of the inbox into the wiki."""

import json
import re
from pathlib import Path

import pytest

from haikei_wiki.organizer import OrganizerError, organize
from haikei_wiki.vocabulary import load_vocabulary

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def seed_inbox(wiki: Path, record: dict) -> Path:
    inbox = wiki / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{record['id']}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def test_organize_writes_pages_updates_index_and_log(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n\n## Chronological Record\n")
    seed_inbox(
        wiki,
        {
            "id": "rec-1",
            "title": "Indexed retrieval wins",
            "entity_type": "claim",
            "content": "Indexed retrieval beats full graph materialization.",
            "links": [{"predicate": "derived_from", "target": "imported/whitepaper"}],
            "provenance": {"agent": "claude", "workspace": "wA"},
            "created_at": "2026-09-07T00:00:00",
        },
    )
    seed_inbox(
        wiki,
        {
            "id": "rec-2",
            "title": "Herdr",
            "entity_type": "entity",
            "content": "A terminal workspace runtime for coding agents.",
            "links": [],
            "provenance": {"agent": "codex", "workspace": "wB"},
            "created_at": "2026-09-07T00:00:01",
        },
    )

    result = organize(
        wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock"
    )

    assert len(result.organized) == 2
    assert not result.rejected

    claim_page = wiki / "wiki" / "claim" / "indexed-retrieval-wins.md"
    assert claim_page.exists()
    content = claim_page.read_text()
    assert "title: Indexed retrieval wins" in content
    assert "category: claim" in content
    assert "- derived_from: [[imported/whitepaper]]" in content

    entity_page = wiki / "wiki" / "entity" / "herdr.md"
    assert entity_page.exists()

    index = (wiki / "index.md").read_text()
    assert "[[claim/indexed-retrieval-wins|Indexed retrieval wins]]" in index
    assert "[[entity/herdr|Herdr]]" in index

    log = (wiki / "log.md").read_text()
    assert re.search(
        r"^## \[\d{4}-\d{2}-\d{2}\] organize \| Indexed retrieval wins -> wiki/claim/indexed-retrieval-wins\.md$",
        log,
        re.M,
    )
    assert re.search(
        r"^## \[\d{4}-\d{2}-\d{2}\] organize \| Herdr -> wiki/entity/herdr\.md$",
        log,
        re.M,
    )

    # inbox drained into processed/
    assert not list((wiki / "inbox").glob("*.json"))
    assert len(list((wiki / "inbox" / "processed").glob("*.json"))) == 2


def test_organize_rejects_out_of_vocabulary_records(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    seed_inbox(
        wiki,
        {
            "id": "bad-1",
            "title": "typed with education tbox",
            "entity_type": "sw:WebDevelopment",
            "content": "should never land",
            "links": [],
            "provenance": {},
            "created_at": "2026-09-07T00:00:00",
        },
    )

    result = organize(
        wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock"
    )

    assert not result.organized
    assert len(result.rejected) == 1
    assert "sw:WebDevelopment" in result.rejected[0][1]
    assert not list((wiki / "inbox").glob("*.json"))
    assert len(list((wiki / "inbox" / "rejected").glob("*.json"))) == 1
    assert not (wiki / "wiki").exists() or not list((wiki / "wiki").rglob("*.md"))


def test_organize_lock_is_exclusive(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    lock = tmp_path / "lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held by another organizer")

    with pytest.raises(OrganizerError, match="another organizer"):
        organize(wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=lock)
