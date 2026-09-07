"""Capture inbox: atomic one-file-per-capture writes + greppable log lines."""

import json
import re
from pathlib import Path

import pytest

from haikei_wiki.capture import Capture, CaptureInbox
from haikei_wiki.context import Provenance
from haikei_wiki.vocabulary import VocabularyViolation, load_vocabulary

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def make_inbox(tmp_path: Path) -> CaptureInbox:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n\n## Chronological Record\n")
    return CaptureInbox(wiki)


def test_capture_lands_one_atomic_file_with_provenance(tmp_path: Path):
    inbox = make_inbox(tmp_path)
    vocab = load_vocabulary(STARTER)
    prov = Provenance(
        agent="opencode",
        worktree="/Users/soypete/code/wt/wiki-plugin",
        workspace="w5B",
        workspace_label="wiki",
        tab="w5B:t1",
        pane="w5B:p1",
    )
    capture = Capture(
        title="herdr popups are session-modal",
        entity_type="claim",
        content="A popup is a singleton session resource, not a Herdr pane.",
        links=[{"predicate": "derived_from", "target": "imported/herdr-docs"}],
        provenance=prov,
    )
    path = inbox.write(capture, vocab)

    assert path.exists()
    assert path.parent == inbox.inbox_dir
    record = json.loads(path.read_text())
    assert record["title"] == "herdr popups are session-modal"
    assert record["entity_type"] == "claim"
    assert record["links"] == [
        {"predicate": "derived_from", "target": "imported/herdr-docs"}
    ]
    assert record["provenance"]["agent"] == "opencode"
    assert record["provenance"]["worktree"] == "/Users/soypete/code/wt/wiki-plugin"
    assert record["provenance"]["workspace"] == "w5B"

    # log.md got one greppable capture line in the established format
    log = (tmp_path / "wiki" / "log.md").read_text()
    assert re.search(
        r"^## \[\d{4}-\d{2}-\d{2}\] capture \| herdr popups are session-modal$",
        log,
        re.M,
    )


def test_capture_outside_vocabulary_rejected_and_writes_nothing(tmp_path: Path):
    inbox = make_inbox(tmp_path)
    vocab = load_vocabulary(STARTER)
    capture = Capture(title="x", entity_type="sw:Beginner", content="y")
    with pytest.raises(VocabularyViolation):
        inbox.write(capture, vocab)
    assert not inbox.inbox_dir.exists() or not list(inbox.inbox_dir.glob("*.json"))
    log = (tmp_path / "wiki" / "log.md").read_text()
    assert "capture" not in log


def test_capture_never_touches_wiki_pages_or_index(tmp_path: Path):
    inbox = make_inbox(tmp_path)
    vocab = load_vocabulary(STARTER)
    inbox.write(Capture(title="t", entity_type="entity", content="c"), vocab)
    wiki_dir = tmp_path / "wiki" / "wiki"
    assert not wiki_dir.exists() or not list(wiki_dir.rglob("*.md"))
    assert not (tmp_path / "wiki" / "index.md").exists()
