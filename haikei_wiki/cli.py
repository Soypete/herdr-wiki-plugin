"""Command-line interface for agent-context lookups.

This is how an AGENT (opencode, claude, codex, ...) searches the wiki from
inside a pane: it runs a command and reads stdout. Unlike the herdr plugin's
search popup (a human UI), this prints results to the terminal.

Usage:
    python3 -m haikei_wiki search <query> [--top-k N] [--json]
    python3 -m haikei_wiki stats
    python3 -m haikei_wiki capture --title T --type T --content C [--link p:t ...]
    python3 -m haikei_wiki organize
"""

import argparse
import json
import sys

from .adapter import LLMWikiAdapter
from .capture import Capture, CaptureInbox, wiki_root
from .context import parse_provenance, resolve_worktree
from .organizer import OrganizerError, organize
from .vocabulary import VocabularyViolation, load_vocabulary


def _search(query: str, top_k: int, as_json: bool) -> int:
    adapter = LLMWikiAdapter(wiki_root())
    results = adapter.search_memory(query, top_k=top_k)
    rows = [
        {
            "path": r.id,
            "source": r.source,
            "score": round(r.score, 3),
            "snippet": " ".join(r.content.split())[:300],
        }
        for r in results
    ]
    if as_json:
        print(json.dumps({"query": query, "results": rows}, indent=2))
    else:
        if not rows:
            print(f"no results for {query!r}")
            return 1
        print(f"{len(rows)} results for {query!r}")
        for row in rows:
            print(f"[{row['score']:.2f}] {row['path']}")
            print(f"    {row['snippet']}")
    return 0


def _stats(as_json: bool) -> int:
    adapter = LLMWikiAdapter(wiki_root())
    s = adapter.get_stats()
    if as_json:
        print(
            json.dumps(
                {"total_items": s.total_items, "size_bytes": s.storage_size_bytes},
                indent=2,
            )
        )
    else:
        print(f"total_items: {s.total_items}")
        print(f"size: {s.storage_size_bytes / 1024 / 1024:.1f} MB")
    return 0


def _capture(args) -> int:
    prov = resolve_worktree(parse_provenance())
    links = []
    for spec in args.link or []:
        predicate, _, target = spec.partition(":")
        links.append({"predicate": predicate.strip(), "target": target.strip()})
    capture = Capture(
        title=args.title,
        entity_type=args.type,
        content=args.content,
        links=links,
        provenance=prov,
    )
    try:
        path = CaptureInbox(wiki_root()).write(capture, load_vocabulary())
    except VocabularyViolation as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 2
    print(str(path))
    return 0


def _organize() -> int:
    try:
        result = organize()
    except OrganizerError as e:
        print(f"organize skipped: {e}", file=sys.stderr)
        return 1
    print(f"organized: {len(result.organized)}  rejected: {len(result.rejected)}")
    for src, rel in result.organized:
        print(f"  {src} -> {rel}")
    for src, reason in result.rejected:
        print(f"  rejected {src}: {reason}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="haikei-wiki", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="search the wiki (agent-context lookup)")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.add_argument("--json", action="store_true")

    p_stats = sub.add_parser("stats", help="wiki statistics")
    p_stats.add_argument("--json", action="store_true")

    p_cap = sub.add_parser("capture", help="capture a note into the inbox")
    p_cap.add_argument("--title", required=True)
    p_cap.add_argument("--type", required=True, dest="type")
    p_cap.add_argument("--content", required=True)
    p_cap.add_argument("--link", action="append", help="predicate:target (repeatable)")

    sub.add_parser("organize", help="reconcile the inbox into the wiki")

    args = parser.parse_args(argv)
    if args.cmd == "search":
        return _search(args.query, args.top_k, args.json)
    if args.cmd == "stats":
        return _stats(args.json)
    if args.cmd == "capture":
        return _capture(args)
    if args.cmd == "organize":
        return _organize()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
