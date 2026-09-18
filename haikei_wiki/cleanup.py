"""Cleanup: safe, exact-selection delete of wiki pages or inbox records.

Safety invariants:
- Requires an exact path or id match — no glob/regex patterns.
- All deletions are logged to log.md.
- Inbox records are moved to inbox/deleted/ (not permanently removed).
- Wiki page deletions remove the file, update index.md, and log.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .capture import log_append, wiki_root


class CleanupError(ValueError):
    pass


@dataclass
class DeleteResult:
    deleted_page: Optional[str] = None
    deleted_inbox: Optional[str] = None
    error: Optional[str] = None


def delete_page(wiki_path: Optional[Path] = None, page_spec: str = "") -> DeleteResult:
    """Delete an exact wiki page by path relative to wiki root.

    The page_spec must match an existing wiki page exactly.  Examples::

        wiki/claim/indexed-retrieval-wins.md
        claim/indexed-retrieval-wins.md
    """
    wiki = Path(wiki_path) if wiki_path else wiki_root()
    wiki_dir = wiki / "wiki"
    index_file = wiki / "index.md"

    if not page_spec.strip():
        return DeleteResult(error="page_spec must be non-empty")

    # Resolve the page_spec to an actual file.
    candidates: list[Path] = []
    spec = page_spec.strip()

    # Try as-is
    p = Path(spec)
    if not p.is_absolute():
        p = wiki / p
    if p.exists() and p.suffix == ".md":
        candidates.append(p)

    # Try under wiki/
    p2 = wiki / "wiki" / spec
    if p2.exists() and p2.suffix == ".md":
        candidates.append(p2)
    elif p2.with_suffix(".md").exists():
        candidates.append(p2.with_suffix(".md"))

    # Try as plain name under wiki/
    if "/" not in spec:
        for md in wiki_dir.rglob(f"{spec}.md"):
            candidates.append(md)
        for md in wiki_dir.rglob(spec):
            if md.suffix == ".md":
                candidates.append(md)

    # Deduplicate
    seen = set()
    unique: list[Path] = []
    for c in candidates:
        s = str(c.resolve())
        if s not in seen:
            seen.add(s)
            unique.append(c)

    if not unique:
        return DeleteResult(error=f"no wiki page matches {page_spec!r}")

    if len(unique) > 1:
        paths = "\n  ".join(str(u.relative_to(wiki)) for u in unique)
        return DeleteResult(
            error=f"page_spec {page_spec!r} is ambiguous; matches:\n  {paths}"
        )

    target = unique[0]
    target_rel = target.relative_to(wiki).as_posix()

    # Read frontmatter for the title
    content = target.read_text()
    title_match = re.search(r"^title:\s*(.+)$", content, re.M)
    title = title_match.group(1).strip() if title_match else target.stem

    # Remove the file
    os.remove(target)

    # Remove from index.md
    if index_file.exists():
        idx = index_file.read_text()
        # Remove lines referencing this page
        patterns = [
            f"[[{target_rel}",
            f"[[{target.relative_to(wiki_dir).as_posix()}",
            f"[[wiki/{target.relative_to(wiki_dir).as_posix()}",
            f"|{title}]]",
        ]
        new_lines = []
        changed = False
        for line in idx.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("- [[") and any(p in stripped for p in patterns):
                changed = True
                continue
            new_lines.append(line)
        if changed:
            index_file.write_text("".join(new_lines))

    # Log
    date = datetime.now().strftime("%Y-%m-%d")
    log_append(wiki / "log.md", f"\n## [{date}] delete page | {title} ({target_rel})")

    return DeleteResult(deleted_page=target_rel)


def delete_inbox(
    wiki_path: Optional[Path] = None, inbox_spec: str = ""
) -> DeleteResult:
    """Delete (move to inbox/deleted/) an exact inbox record by id.

    The inbox_spec must match a filename under inbox/ exactly (with or
    without .json suffix).
    """
    wiki = Path(wiki_path) if wiki_path else wiki_root()
    inbox_dir = wiki / "inbox"
    deleted_dir = inbox_dir / "deleted"

    if not inbox_spec.strip():
        return DeleteResult(error="inbox_spec must be non-empty")

    spec = inbox_spec.strip().rstrip(".json")

    # Find exact match
    target = inbox_dir / f"{spec}.json"
    if not target.exists():
        # Check for partial match (warn but don't allow)
        matches = sorted(inbox_dir.glob(f"{spec}*.json"))
        if not matches:
            return DeleteResult(error=f"no inbox record matches {inbox_spec!r}")
        names = "\n  ".join(m.name for m in matches)
        if len(matches) == 1 and matches[0].stem == spec:
            target = matches[0]
        else:
            return DeleteResult(
                error=f"inbox_spec {inbox_spec!r} is not exact; matches:\n  {names}"
            )

    # Read record for logging
    try:
        record = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        record = {}

    record_id = record.get("id", target.stem)
    record_title = record.get("title", target.stem)

    # Move to deleted/
    deleted_dir.mkdir(parents=True, exist_ok=True)
    dest = deleted_dir / target.name
    n = 1
    while dest.exists():
        dest = deleted_dir / f"{n}-{target.name}"
        n += 1
    os.replace(target, dest)

    # Log
    date = datetime.now().strftime("%Y-%m-%d")
    log_append(
        wiki / "log.md",
        f"\n## [{date}] delete inbox | {record_title} ({record_id})",
    )

    return DeleteResult(deleted_inbox=record_id)
