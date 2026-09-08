#!/usr/bin/env python3
"""Wiki skill handler for OpenCode — agent-context lookup into the LLM-Wiki.

Thin wrapper over `haikei_wiki.cli`. Ergonomic default: `/wiki <query>` is
treated as `/wiki search <query>`, matching the `/llmwiki` pattern.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from haikei_wiki.cli import main  # noqa: E402

SUBCOMMANDS = {"search", "stats", "capture", "organize"}


def run() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: /wiki <query> [--top-k N] [--json]")
        print("       /wiki search|stats|capture|organize ...")
        return
    if argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["search"] + argv
    sys.exit(main(argv))


if __name__ == "__main__":
    run()
