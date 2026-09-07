#!/usr/bin/env python3
"""Action: organize. Runs the single-writer organizer pass over the inbox."""

import _bootstrap  # noqa: F401

from haikei_wiki.organizer import OrganizerError, organize


def main() -> int:
    try:
        result = organize()
    except OrganizerError as e:
        print(f"organize skipped: {e}")
        return 1
    print(f"organized: {len(result.organized)}")
    for src, rel in result.organized:
        print(f"  {src} -> {rel}")
    print(f"rejected: {len(result.rejected)}")
    for src, reason in result.rejected:
        print(f"  {src}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
