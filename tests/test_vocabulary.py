"""Closed capture vocabulary: enforcement at the write boundary."""

import json
from pathlib import Path

import pytest

from haikei_wiki.vocabulary import (
    Vocabulary,
    VocabularyViolation,
    load_vocabulary,
)

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def test_starter_vocabulary_loads():
    vocab = load_vocabulary(STARTER)
    assert {
        "source",
        "claim",
        "entity",
        "contradiction",
        "decision",
    } <= vocab.entity_types
    assert {
        "derived_from",
        "contradicts",
        "supports",
        "about",
        "relates_to",
    } <= vocab.link_predicates


def test_unknown_entity_type_rejected_with_constraint_named():
    vocab = load_vocabulary(STARTER)
    with pytest.raises(VocabularyViolation) as exc:
        vocab.check_capture("bogus", [])
    msg = str(exc.value)
    assert "entity_type 'bogus'" in msg
    assert "constraint" in msg
    assert "entity_type must be one of the loaded capture vocabulary types" in msg


def test_unknown_link_predicate_rejected_with_constraint_named():
    vocab = load_vocabulary(STARTER)
    with pytest.raises(VocabularyViolation) as exc:
        vocab.check_capture(
            "claim", [{"predicate": "sw:hasPrerequisite", "target": "x"}]
        )
    msg = str(exc.value)
    assert "link predicate 'sw:hasPrerequisite'" in msg
    assert (
        "link predicate must be one of the loaded capture vocabulary predicates" in msg
    )


def test_education_tbox_terms_are_not_in_the_capture_vocabulary():
    vocab = load_vocabulary(STARTER)
    for term in ("sw:Beginner", "sw:WebDevelopment", "sw:hasLesson"):
        assert term not in vocab.entity_types
        assert term not in vocab.link_predicates


def test_missing_entity_type_rejected_no_default_coercion():
    vocab = load_vocabulary(STARTER)
    with pytest.raises(VocabularyViolation) as exc:
        vocab.check_capture("", [])
    assert "no default is applied" in str(exc.value)


def test_link_without_target_rejected():
    vocab = load_vocabulary(STARTER)
    with pytest.raises(VocabularyViolation):
        vocab.check_capture("claim", [{"predicate": "about", "target": ""}])


def test_valid_capture_passes():
    vocab = load_vocabulary(STARTER)
    vocab.check_capture(
        "claim",
        [{"predicate": "derived_from", "target": "imported/whitepaper"}],
    )


def test_coordination_entity_types_are_in_vocabulary():
    vocab = load_vocabulary(STARTER)
    assert {
        "blocker",
        "handoff",
        "ack",
        "release",
        "contract_change",
    } <= vocab.entity_types


def test_coordination_link_predicates_are_in_vocabulary():
    vocab = load_vocabulary(STARTER)
    assert {"answers", "acknowledges", "blocks"} <= vocab.link_predicates


def test_coordination_capture_chain_passes():
    """A request -> decision -> ack chain using the new predicates/types."""
    vocab = load_vocabulary(STARTER)
    vocab.check_capture("handoff", [{"predicate": "acknowledges", "target": "req-1"}])
    vocab.check_capture("decision", [{"predicate": "answers", "target": "handoff-1"}])
    vocab.check_capture("ack", [{"predicate": "acknowledges", "target": "decision-1"}])
    vocab.check_capture("blocker", [{"predicate": "blocks", "target": "task-9"}])


def test_new_types_accepted_at_capture_write_boundary(tmp_path):
    """Each new coordination type actually lands in the inbox via CaptureInbox."""
    from haikei_wiki.capture import Capture, CaptureInbox

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    inbox = CaptureInbox(wiki)
    vocab = load_vocabulary(STARTER)

    for entity_type in ("blocker", "handoff", "ack", "release", "contract_change"):
        inbox.write(
            Capture(title=f"t-{entity_type}", entity_type=entity_type, content="c"),
            vocab,
        )

    landed = {json.loads(p.read_text())["entity_type"] for p in inbox.pending()}
    assert {
        "blocker",
        "handoff",
        "ack",
        "release",
        "contract_change",
    } <= landed


def test_new_predicates_accepted_at_capture_write_boundary(tmp_path):
    from haikei_wiki.capture import Capture, CaptureInbox

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    inbox = CaptureInbox(wiki)
    vocab = load_vocabulary(STARTER)

    capture = Capture(
        title="request 7 acked",
        entity_type="ack",
        content="ack'd",
        links=[
            {"predicate": "answers", "target": "req-7"},
            {"predicate": "acknowledges", "target": "handoff-7"},
            {"predicate": "blocks", "target": "task-7"},
        ],
    )
    inbox.write(capture, vocab)
    landed = json.loads(inbox.pending()[0].read_text())
    assert landed["entity_type"] == "ack"
    assert landed["links"][0]["predicate"] == "answers"
