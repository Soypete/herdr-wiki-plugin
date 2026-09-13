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
    python3 -m haikei_wiki supersede <page> --by <page-or-url> [--reason "..."]
    python3 -m haikei_wiki withdraw <page> --reason "..."
"""

import argparse
import json
import sys
from pathlib import Path

from .adapter import LLMWikiAdapter
from .audit import (
    CONF_JUDGMENT,
    CONF_LIKELY,
    CONF_POSSIBLY,
    run_audit,
)
from .capture import Capture, CaptureInbox, wiki_root
from .context import parse_provenance, resolve_worktree
from .lifecycle import (
    LIFECYCLE_STATES,
    LifecycleError,
    page_status,
    supersede,
    withdraw,
)
from .organizer import OrganizerError, organize
from .vocabulary import VocabularyViolation, load_vocabulary

# Superseded/withdrawn pages still surface in search (the history is the point)
# but rank below current ones and are labelled so a worker sees at a glance that
# a hit is historical.
_STATUS_DOWNRANK = 0.5

_CONF_ORDER = (CONF_LIKELY, CONF_POSSIBLY, CONF_JUDGMENT)


def _search(query: str, top_k: int, as_json: bool, include_inbox: bool = True) -> int:
    adapter = LLMWikiAdapter(wiki_root())
    # Pull a wider pool so status down-ranking can reorder before we truncate:
    # a superseded page must not displace a current one from the final top_k.
    pool = max(top_k * 3, top_k + 10)
    results = adapter.search_memory(query, top_k=pool, include_inbox=include_inbox)
    rows = []
    for r in results:
        status = ""
        # Only settled wiki pages carry frontmatter; inbox records do not.
        if not r.id.startswith("inbox:") and not r.id.endswith("index.md"):
            p = Path(r.id)
            if p.is_file():
                status = page_status(p)
        score = r.score
        if status in LIFECYCLE_STATES:
            score *= _STATUS_DOWNRANK
        rows.append(
            {
                "path": r.id,
                "source": r.source,
                "score": round(score, 3),
                "snippet": " ".join(r.content.split())[:300],
                "status": status,
            }
        )
    rows.sort(key=lambda x: x["score"], reverse=True)
    rows = rows[:top_k]
    if as_json:
        print(json.dumps({"query": query, "results": rows}, indent=2))
    else:
        if not rows:
            print(f"no results for {query!r}")
            return 1
        print(f"{len(rows)} results for {query!r}")
        for row in rows:
            label = f" [{row['status']}]" if row["status"] else ""
            print(f"[{row['score']:.2f}]{label} {row['path']}")
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


def _audit(as_json: bool, stale_days: float, repo_dirs: list) -> int:
    # Read-only: reports candidates and exits. Never modifies or deletes a page.
    report = run_audit(wiki_root(), stale_days=stale_days, extra_repo_dirs=repo_dirs)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        groups = report.by_confidence()
        if not report.findings:
            print(
                f"no stale candidates among {report.pages_scanned} coordination pages"
            )
            return 0
        print(
            f"{len(report.findings)} candidates among {report.pages_scanned} coordination pages"
        )
        for conf in _CONF_ORDER:
            items = groups.get(conf, [])
            if not items:
                continue
            print(f"\n{conf}")
            for f in items:
                print(f"  {f.page}  [{f.check}]")
                print(f"      {f.evidence}")
                if f.related:
                    print(f"      related: {f.related}")
    return 0


def _supersede(page_path: str, by: str, reason) -> int:
    try:
        path = supersede(_resolve_page(page_path), by, reason)
    except LifecycleError as e:
        print(f"supersede: {e}", file=sys.stderr)
        return 2
    print(f"superseded {path}")
    return 0


def _withdraw(page_path: str, reason) -> int:
    try:
        path = withdraw(_resolve_page(page_path), reason)
    except LifecycleError as e:
        print(f"withdraw: {e}", file=sys.stderr)
        return 2
    print(f"withdrew {path}")
    return 0


def _resolve_page(page_path: str) -> Path:
    p = Path(page_path)
    return p if p.is_absolute() else wiki_root() / p


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

    p_audit = sub.add_parser(
        "audit",
        help="read-only: find coordination pages that no longer describe reality",
    )
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument(
        "--stale-days",
        type=float,
        default=7,
        help="age threshold for the unresolved-claim check (default 7)",
    )
    p_audit.add_argument(
        "--repo-dir",
        action="append",
        default=[],
        help="extra directory to search for a repo (repeatable)",
    )

    p_super = sub.add_parser(
        "supersede", help="mark a page superseded by another page/URL"
    )
    p_super.add_argument("page_path")
    p_super.add_argument(
        "--by", required=True, help="page path or URL that supersedes it"
    )
    p_super.add_argument("--reason", help="optional reason")

    p_withdraw = sub.add_parser(
        "withdraw", help="mark a page withdrawn (was wrong when written)"
    )
    p_withdraw.add_argument("page_path")
    p_withdraw.add_argument("--reason", required=True)

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
        return _audit(args.json, args.stale_days, args.repo_dir)
    if args.cmd == "supersede":
        return _supersede(args.page_path, args.by, args.reason)
    if args.cmd == "withdraw":
        return _withdraw(args.page_path, args.reason)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
