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


# --- lifecycle status on inbox records + #13 recovery ----------------------


def _base_record(rid, title, content):
    return {
        "id": rid,
        "title": title,
        "entity_type": "claim",
        "content": content,
        "links": [],
        "provenance": {"agent": "test"},
        "created_at": "2026-10-01T14:44:48",
    }


def test_organize_files_superseded_status_with_the_page(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    rec = _base_record("rec-sup", "stale capture", "superseded capture body")
    rec["status"] = "superseded"
    rec["superseded_by"] = "wiki/claim/newer.md"
    seed_inbox(wiki, rec)

    result = organize(wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock")

    assert len(result.organized) == 1
    from haikei_wiki.lifecycle import parse_frontmatter

    page = wiki / "wiki" / "claim" / "stale-capture.md"
    fields, _, _ = parse_frontmatter(page.read_text())
    assert fields["status"] == "superseded"
    assert fields["superseded_by"] == "wiki/claim/newer.md"
    assert not list((wiki / "inbox").glob("*.json"))


def test_organize_files_withdrawn_status_with_the_page(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    rec = _base_record("rec-wd", "wrong capture", "withdrawn capture body")
    rec["status"] = "withdrawn"
    rec["reason"] = "was wrong when captured"
    seed_inbox(wiki, rec)

    organize(wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock")

    from haikei_wiki.lifecycle import parse_frontmatter

    page = wiki / "wiki" / "claim" / "wrong-capture.md"
    fields, _, _ = parse_frontmatter(page.read_text())
    assert fields["status"] == "withdrawn"
    assert fields["reason"] == "was wrong when captured"


def test_organize_recovers_frontmattered_json_records(tmp_path: Path):
    """Records corrupted by the pre-#13 supersede/withdraw bug (YAML
    frontmatter prepended to the JSON) are salvaged, not rejected: the JSON
    parses after stripping the frontmatter, and the frontmatter status is
    applied to the filed page."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    rec = _base_record("rec-broken", "double captured", "salvage me")
    rec["status"] = "superseded"
    rec["superseded_by"] = "inbox/20261001T14533196721-other.json"
    payload = json.dumps(rec, indent=2)
    inbox = wiki / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "rec-broken.json").write_text(
        "\n".join(
            [
                "---",
                "status: superseded",
                "superseded_by: inbox/20261001T14533196721-other.json",
                "---",
                "",
                payload,
            ]
        )
        + "\n"
    )

    result = organize(wiki_path=wiki, vocab=load_vocabulary(STARTER), lock_path=tmp_path / "lock")

    assert len(result.organized) == 1, result.rejected
    assert not result.rejected
    from haikei_wiki.lifecycle import parse_frontmatter

    page = wiki / "wiki" / "claim" / "double-captured.md"
    fields, _, _ = parse_frontmatter(page.read_text())
    assert fields["status"] == "superseded"
    assert fields["superseded_by"] == "inbox/20261001T14533196721-other.json"
    # the recovered record left the pending inbox
    assert not list(inbox.glob("*.json"))
