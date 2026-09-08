#!/usr/bin/env python3
"""Wiki skill handler for OpenCode — agent-context lookup into the LLM-Wiki.

Delegates to the haikei_wiki CLI. Resolves the repo from this file's location
(in-repo use); if the package isn't importable (skill copied elsewhere), falls
back to the `wiki` launcher on PATH.
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from haikei_wiki.cli import main
except ImportError:  # pragma: no cover - skill copied outside the repo
    main = None

SUBCOMMANDS = {"search", "stats", "capture", "organize"}


def run() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: /wiki <query> [--top-k N] [--json]")
        print("       /wiki search|stats|capture|organize ...")
        return
    if argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["search"] + argv

    if main is not None:
        sys.exit(main(argv))

    wiki = shutil.which("wiki")
    if wiki:
        sys.exit(subprocess.call([wiki] + argv))
    print("error: haikei_wiki not importable and `wiki` not on PATH", file=sys.stderr)
    sys.exit(3)


if __name__ == "__main__":
    run()
