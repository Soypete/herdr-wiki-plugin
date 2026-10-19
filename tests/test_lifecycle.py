"""Lifecycle: supersede / withdraw write only the status fields, never the body."""

import json
from pathlib import Path

from haikei_wiki.lifecycle import (
    LifecycleError,
    page_status,
    parse_frontmatter,
    supersede,
    withdraw,
)

PAGE = """---
title: drift/credential-delivery-scoped-by-org-not-workspace
category: contradiction
created: 2026-09-12T17:55:06.419770
---

THE DEVIATION: validateRuntimeToken in cmd/abac-engine/credential_delivery.go:406-418
resolves a runtime token. It never reads the key's workspace_id.

## Links

- about: [[plan/goal]]
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_supersede_sets_status_and_superseded_by(tmp_path):
    p = _write(tmp_path, "drift.md", PAGE)
    supersede(p, by="wiki/decision/d-014.md", reason="fixed in bbbaab37")

    text = p.read_text()
    fields, _, body = parse_frontmatter(text)
    assert fields["status"] == "superseded"
    assert fields["superseded_by"] == "wiki/decision/d-014.md"
    assert fields["reason"] == "fixed in bbbaab37"
    # title, category, created untouched
    assert fields["title"] == "drift/credential-delivery-scoped-by-org-not-workspace"
    assert fields["category"] == "contradiction"
    assert fields["created"] == "2026-09-12T17:55:06.419770"
    # body untouched
    assert "It never reads the key's workspace_id." in body
    assert "- about: [[plan/goal]]" in body


def test_supersede_requires_by(tmp_path):
    p = _write(tmp_path, "drift.md", PAGE)
    try:
        supersede(p, by="")
        assert False, "expected LifecycleError"
    except LifecycleError:
        pass


def test_withdraw_sets_status_and_reason(tmp_path):
    p = _write(tmp_path, "wrong.md", PAGE)
    withdraw(p, reason="premise was false; see X")

    text = p.read_text()
    fields, _, body = parse_frontmatter(text)
    assert fields["status"] == "withdrawn"
    assert fields["reason"] == "premise was false; see X"
    assert fields["title"] == "drift/credential-delivery-scoped-by-org-not-workspace"
    assert "It never reads the key's workspace_id." in body


def test_withdraw_requires_reason(tmp_path):
    p = _write(tmp_path, "wrong.md", PAGE)
    try:
        withdraw(p, reason="")
        assert False, "expected LifecycleError"
    except LifecycleError:
        pass


def test_missing_page_raises(tmp_path):
    try:
        supersede(tmp_path / "nope.md", by="x")
        assert False, "expected LifecycleError"
    except LifecycleError:
        pass


def test_page_status_reads_frontmatter(tmp_path):
    p = _write(tmp_path, "cur.md", PAGE)
    assert page_status(p) == ""  # absent status means current
    supersede(p, by="y")
    assert page_status(p) == "superseded"
    withdraw(p, reason="z")
    assert page_status(p) == "withdrawn"


def test_supersede_quotes_reason_with_colon_space(tmp_path):
    p = _write(tmp_path, "d.md", PAGE)
    supersede(p, by="x", reason="see D-014: new keys only")
    fields, _, _ = parse_frontmatter(p.read_text())
    assert fields["reason"] == "see D-014: new keys only"


# --- inbox JSON records (issue #13) ----------------------------------------


def _inbox_record(wiki: Path, rid: str = "20261001T144448933485-62364054") -> Path:
    inbox = wiki / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / f"{rid}.json"
    p.write_text(
        json.dumps(
            {
                "id": rid,
                "title": "fresh capture",
                "entity_type": "claim",
                "content": "pending capture body",
                "links": [],
                "provenance": {"agent": "test"},
                "created_at": "2026-10-01T14:44:48",
            }
        )
    )
    return p


def test_supersede_inbox_record_sets_json_not_frontmatter(tmp_path):
    """The record must stay valid JSON: no YAML frontmatter prepended, or
    organize rejects the record and loses the supersession (issue #13)."""
    p = _inbox_record(tmp_path)
    supersede(p, by="inbox/20261001T14533196721-test.json", reason="captured twice")

    text = p.read_text()
    assert not text.startswith("---"), "frontmatter must never land in a .json"
    record = json.loads(text)
    assert record["status"] == "superseded"
    assert record["superseded_by"] == "inbox/20261001T14533196721-test.json"
    assert record["reason"] == "captured twice"
    assert record["id"] == "20261001T144448933485-62364054"


def test_withdraw_inbox_record_sets_json(tmp_path):
    p = _inbox_record(tmp_path)
    withdraw(p, reason="was wrong when captured")
    record = json.loads(p.read_text())
    assert record["status"] == "withdrawn"
    assert record["reason"] == "was wrong when captured"


def test_supersede_inbox_corrupt_record_raises_not_mangles(tmp_path):
    p = _inbox_record(tmp_path)
    p.write_text("{ not json")
    try:
        supersede(p, by="x")
        assert False, "expected LifecycleError"
    except LifecycleError:
        pass
    # file untouched
    assert p.read_text() == "{ not json"
