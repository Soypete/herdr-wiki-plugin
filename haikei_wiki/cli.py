"""Command-line interface for agent-context lookups.

This is how an AGENT (opencode, claude, codex, ...) searches the wiki from
inside a pane: it runs a command and reads stdout. Unlike the herdr plugin's
search popup (a human UI), this prints results to the terminal.

Usage:
    python3 -m haikei_wiki search <query> [--top-k N] [--no-inbox] [--json]
    python3 -m haikei_wiki stats
    python3 -m haikei_wiki capture --title T --type T --content C [--link p:t ...]
    python3 -m haikei_wiki organize
    python3 -m haikei_wiki audit [--json] [--stale-days N]
    python3 -m haikei_wiki delete page <path> [--force]
    python3 -m haikei_wiki delete inbox <id> [--force]
"""

import argparse
import json
import sys

from .adapter import LLMWikiAdapter
from .audit import audit
from .capture import Capture, CaptureInbox, wiki_root
from .cleanup import CleanupError, delete_inbox, delete_page
from .context import parse_provenance, resolve_worktree
from .organizer import OrganizerError, organize
from .vocabulary import VocabularyViolation, load_vocabulary


def _search(query: str, top_k: int, as_json: bool, include_inbox: bool = True) -> int:
    adapter = LLMWikiAdapter(wiki_root())
    results = adapter.search_memory(query, top_k=top_k, include_inbox=include_inbox)
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


def _audit(as_json: bool, stale_days: int) -> int:
    report = audit(stale_days=stale_days)
    if as_json:
        print(
            json.dumps(
                {
                    "orphans": report.orphans,
                    "broken_links": [
                        {"source": s, "target": t} for s, t in report.broken_links
                    ],
                    "unindexed": report.unindexed,
                    "empty_pages": report.empty_pages,
                    "stale_inbox": report.stale_inbox,
                    "total_pages": report.total_pages,
                    "total_inbox": report.total_inbox,
                },
                indent=2,
            )
        )
    else:
        print(f"wiki audit ({report.total_pages} pages, {report.total_inbox} inbox)")
        if report.orphans:
            print(f"\norphans ({report.total_orphans}):")
            for p in report.orphans:
                print(f"  {p}")
        if report.broken_links:
            print(f"\nbroken links ({report.total_broken_links}):")
            for src, tgt in report.broken_links:
                print(f"  {src} -> [[{tgt}]]")
        if report.unindexed:
            print(f"\nunindexed ({report.total_unindexed}):")
            for p in report.unindexed:
                print(f"  {p}")
        if report.empty_pages:
            print(f"\nempty/trivial ({report.total_empty}):")
            for p in report.empty_pages:
                print(f"  {p}")
        if report.stale_inbox:
            print(f"\nstale inbox records ({report.total_stale}):")
            for p in report.stale_inbox:
                print(f"  {p}")
        if not any(
            [
                report.orphans,
                report.broken_links,
                report.unindexed,
                report.empty_pages,
                report.stale_inbox,
            ]
        ):
            print("no issues found")
    return 0


def _delete(args) -> int:
    from .cleanup import delete_page, delete_inbox

    if args.delete_target == "page":
        result = delete_page(page_spec=args.spec)
    elif args.delete_target == "inbox":
        result = delete_inbox(inbox_spec=args.spec)
    else:
        print(f"unknown delete target: {args.delete_target}", file=sys.stderr)
        return 2

    if result.error:
        print(f"ERROR: {result.error}", file=sys.stderr)
        return 1
    if result.deleted_page:
        print(f"deleted page: {result.deleted_page}")
    if result.deleted_inbox:
        print(f"deleted inbox record: {result.deleted_inbox}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="haikei-wiki", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="search the wiki (agent-context lookup)")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.add_argument(
        "--no-inbox",
        action="store_true",
        help="exclude pending inbox records (by default they are included)",
    )
    p_search.add_argument("--json", action="store_true")

    p_stats = sub.add_parser("stats", help="wiki statistics")
    p_stats.add_argument("--json", action="store_true")

    p_cap = sub.add_parser("capture", help="capture a note into the inbox")
    p_cap.add_argument("--title", required=True)
    p_cap.add_argument("--type", required=True, dest="type")
    p_cap.add_argument("--content", required=True)
    p_cap.add_argument("--link", action="append", help="predicate:target (repeatable)")

    sub.add_parser("organize", help="reconcile the inbox into the wiki")

    p_audit = sub.add_parser("audit", help="scan the wiki for structural issues")
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument(
        "--stale-days",
        type=int,
        default=7,
        help="stale inbox threshold in days (default 7)",
    )

    p_del = sub.add_parser("delete", help="delete a wiki page or inbox record")
    p_del.add_argument(
        "delete_target",
        choices=["page", "inbox"],
        help="what to delete: 'page' or 'inbox'",
    )
    p_del.add_argument("spec", help="exact page path or inbox record id")

    args = parser.parse_args(argv)
    if args.cmd == "search":
        return _search(args.query, args.top_k, args.json, not args.no_inbox)
    if args.cmd == "stats":
        return _stats(args.json)
    if args.cmd == "capture":
        return _capture(args)
    if args.cmd == "organize":
        return _organize()
    if args.cmd == "audit":
        return _audit(args.json, args.stale_days)
    if args.cmd == "delete":
        return _delete(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
