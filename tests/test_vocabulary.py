"""Closed capture vocabulary: enforcement at the write boundary."""

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
