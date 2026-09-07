#!/usr/bin/env python3
"""Pane: wiki search UI (popup).

Non-interactive when WIKI_SEARCH_QUERY is set: prints results, records them
under $HERDR_PLUGIN_STATE_DIR/last_search.json, and exits (closing the
popup). Otherwise runs an interactive query loop.
"""

import _bootstrap  # noqa: F401

import json
import os
from pathlib import Path

from haikei_wiki.capture import wiki_root
from haikei_wiki.context import parse_provenance
from haikei_wiki.adapter import LLMWikiAdapter
from haikei_wiki.organizer import state_dir


def do_search(query: str) -> list[dict]:
    adapter = LLMWikiAdapter(wiki_root())
    results = adapter.search_memory(query, top_k=10)
    return [
        {
            "id": r.id,
            "source": r.source,
            "score": r.score,
            "snippet": r.content[:200].replace("\n", " "),
        }
        for r in results
    ]


def print_results(query: str, results: list[dict]) -> None:
    print(f"=== wiki search: {query!r} ({len(results)} results) ===")
    if not results:
        print("  (no results)")
    for r in results:
        print(f"  [{r['score']:.1f}] {r['id']}")
        print(f"        {r['snippet']}")
    print()


def main() -> int:
    query = os.environ.get("WIKI_SEARCH_QUERY", "").strip()
    if query:
        results = do_search(query)
        print_results(query, results)
        prov = parse_provenance().as_dict()
        out = state_dir() / "last_search.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"query": query, "context": prov, "results": results}, indent=2)
        )
        print(f"results recorded: {out}")
        return 0

    print("wiki search (q to quit)")
    while True:
        try:
            q = input("wiki> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q in {"q", "quit", "exit"}:
            break
        results = do_search(q)
        print_results(q, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
