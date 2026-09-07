#!/usr/bin/env python3
"""Action: wiki capture.

Non-interactive mode (for tests/automation): pass --title, --type and
--content; the capture is written directly to the inbox.

Default mode: opens the capture popup pane, which pre-fills content from the
selected text and asks for a title, an entity type from the loaded
vocabulary, and optional links.
"""

import _bootstrap  # noqa: F401

import argparse

from haikei_wiki.capture import Capture, CaptureInbox, wiki_root
from haikei_wiki.context import parse_provenance, resolve_worktree
from haikei_wiki.herdr import HerdrError, run
from haikei_wiki.vocabulary import VocabularyViolation, load_vocabulary

PLUGIN_ID = "haikei.wiki"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title")
    parser.add_argument("--type", dest="entity_type")
    parser.add_argument("--content")
    parser.add_argument(
        "--link",
        action="append",
        default=[],
        help="link as 'predicate:target' (repeatable)",
    )
    args = parser.parse_args()

    if args.title and args.entity_type and args.content:
        prov = resolve_worktree(parse_provenance())
        links = []
        for spec in args.link:
            predicate, _, target = spec.partition(":")
            links.append({"predicate": predicate, "target": target})
        inbox = CaptureInbox(wiki_root())
        capture = Capture(
            title=args.title,
            entity_type=args.entity_type,
            content=args.content,
            links=links,
            provenance=prov,
        )
        try:
            path = inbox.write(capture, load_vocabulary())
        except VocabularyViolation as e:
            print(f"REJECTED: {e}")
            return 2
        print(f"captured: {path}")
        return 0

    result = run(
        ["plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "capture"]
    )
    print(f"opened capture popup")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
