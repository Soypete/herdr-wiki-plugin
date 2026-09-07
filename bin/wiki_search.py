#!/usr/bin/env python3
"""Action: wiki search. Opens the search popup pane.

The query comes from the selected text in HERDR_PLUGIN_CONTEXT_JSON when
available; otherwise the popup opens in interactive mode.
"""

import _bootstrap  # noqa: F401

from haikei_wiki.context import parse_provenance
from haikei_wiki.herdr import run

PLUGIN_ID = "haikei.wiki"


def main() -> int:
    prov = parse_provenance()
    query = (prov.selected_text or "").strip()

    args = ["plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "search"]
    if query:
        args += ["--env", f"WIKI_SEARCH_QUERY={query}"]
    result = run(args)
    print(f"opened search popup (query={query!r})")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
