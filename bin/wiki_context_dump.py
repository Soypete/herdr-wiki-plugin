#!/usr/bin/env python3
"""Action: context-dump. Prints the runtime plugin environment for debugging.

Used to verify the real field names of HERDR_PLUGIN_CONTEXT_JSON in a live
pane. Prints every HERDR_* env var (context JSON in full).
"""

import _bootstrap  # noqa: F401

import json
import os

from haikei_wiki.context import parse_provenance, resolve_worktree


def main() -> int:
    for k in sorted(os.environ):
        if k.startswith("HERDR_"):
            v = os.environ[k]
            if k == "HERDR_PLUGIN_CONTEXT_JSON" and v:
                try:
                    v = json.dumps(json.loads(v), indent=2)
                except json.JSONDecodeError:
                    pass
            print(f"{k}={v}")
    print("--- parsed provenance (worktree resolved via herdr worktree list) ---")
    print(json.dumps(resolve_worktree(parse_provenance()).as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
