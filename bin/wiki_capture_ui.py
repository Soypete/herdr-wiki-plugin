#!/usr/bin/env python3
"""Pane: wiki capture UI (popup).

Shows provenance from HERDR_PLUGIN_CONTEXT_JSON, pre-fills content from the
selected text, and asks for a title, an entity type chosen from the loaded
vocabulary (no default is applied), and optional links. Writes one atomic
inbox record and appends a log.md entry.
"""

import _bootstrap  # noqa: F401

import os

from haikei_wiki.capture import Capture, CaptureInbox, wiki_root
from haikei_wiki.context import parse_provenance, resolve_worktree
from haikei_wiki.vocabulary import VocabularyViolation, load_vocabulary


def _noninteractive() -> dict | None:
    """Capture fully specified via env (used to drive captures from a pane)."""
    title = os.environ.get("WIKI_CAPTURE_TITLE", "").strip()
    entity_type = os.environ.get("WIKI_CAPTURE_TYPE", "").strip()
    content = os.environ.get("WIKI_CAPTURE_CONTENT", "").strip()
    if not (title and entity_type and content):
        return None
    links = []
    for spec in os.environ.get("WIKI_CAPTURE_LINKS", "").split(";"):
        spec = spec.strip()
        if not spec:
            continue
        predicate, _, target = spec.partition(":")
        links.append({"predicate": predicate.strip(), "target": target.strip()})
    return {
        "title": title,
        "entity_type": entity_type,
        "content": content,
        "links": links,
    }


def main() -> int:
    prov = resolve_worktree(parse_provenance())
    vocab = load_vocabulary()

    spec = _noninteractive()
    if spec is not None:
        try:
            inbox = CaptureInbox(wiki_root())
            path = inbox.write(
                Capture(
                    title=spec["title"],
                    entity_type=spec["entity_type"],
                    content=spec["content"],
                    links=spec["links"],
                    provenance=prov,
                ),
                vocab,
            )
        except VocabularyViolation as e:
            print(f"REJECTED: {e}")
            return 2
        print("captured (non-interactive):")
        for k, v in prov.as_dict().items():
            print(f"  provenance.{k}: {v}")
        print(f"  path: {path}")
        return 0

    print("wiki capture")
    print("provenance:")
    for k, v in prov.as_dict().items():
        if k == "selected_text":
            continue
        print(f"  {k}: {v}")

    selected = (prov.selected_text or "").strip()
    if selected:
        print(f"\nselected text ({len(selected)} chars):")
        print(selected[:2000])

    try:
        title = input("\ntitle> ").strip()
        if not title and selected:
            title = selected.splitlines()[0][:80].strip()
        if not title:
            print("REJECTED: title must be non-empty")
            return 2

        types = sorted(vocab.entity_types)
        print("\nentity type (choose one - no default is applied):")
        for i, t in enumerate(types, 1):
            print(f"  {i}. {t}")
        choice = input("type> ").strip()
        try:
            entity_type = types[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"REJECTED: type must be one of: {', '.join(types)}")
            return 2

        content = selected
        if not content:
            print("content> (end with a line containing only '.')")
            lines = []
            while True:
                line = input()
                if line.strip() == ".":
                    break
                lines.append(line)
            content = "\n".join(lines).strip()

        links = []
        raw_links = input("links> (predicate:target;... or empty)> ").strip()
        if raw_links:
            for spec in raw_links.split(";"):
                spec = spec.strip()
                if not spec:
                    continue
                predicate, _, target = spec.partition(":")
                links.append({"predicate": predicate.strip(), "target": target.strip()})

        inbox = CaptureInbox(wiki_root())
        capture = Capture(
            title=title,
            entity_type=entity_type,
            content=content,
            links=links,
            provenance=prov,
        )
        path = inbox.write(capture, vocab)
        print(f"\ncaptured: {path}")
        print("run the organize action to reconcile the inbox")
        return 0
    except VocabularyViolation as e:
        print(f"REJECTED: {e}")
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
