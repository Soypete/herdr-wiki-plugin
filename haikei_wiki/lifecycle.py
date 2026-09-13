"""Page lifecycle: supersede / withdraw, and status-aware search helpers.

The audit only reports. Lifecycle state is written here, by explicit human
command (`wiki supersede`, `wiki withdraw`), so the graph keeps its
single-writer discipline: `organize` writes pages, and lifecycle commands write
only the three status fields in a page's frontmatter.

Lifecycle states recorded in frontmatter:

- **current** — default; a missing `status` means current
- **superseded** — was true, no longer describes the code; must name what
  superseded it (`superseded_by`)
- **withdrawn** — was wrong when written; must say why (`reason`)

`title`, `category`, and `created` are never touched.
"""

import re
from pathlib import Path

SUPERSEDED = "superseded"
WITHDRAWN = "withdrawn"
LIFECYCLE_STATES = (SUPERSEDED, WITHDRAWN)


class LifecycleError(ValueError):
    """A lifecycle command could not be applied (bad state, bad page)."""


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SIMPLE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:#+# -]+$")


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Split a wiki page into (frontmatter dict, raw frontmatter, body).

    Returns ({}, "", text) when the page has no frontmatter, so callers can
    still rewrite it (the lifecycle commands always write frontmatter).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, "", text
    raw = m.group(1)
    body = text[m.end() :]
    fields: dict = {}
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            if key.strip():
                fields[key.strip()] = _unquote(value.strip())
    return fields, raw, body


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return value


def page_status(path: Path) -> str:
    """Read the frontmatter `status` of a page; "" when unset."""
    try:
        text = path.read_text()
    except OSError:
        return ""
    fields, _, _ = parse_frontmatter(text)
    return str(fields.get("status", "")).strip()


def _fmt_value(value: str) -> str:
    value = value.strip()
    if not value:
        return '""'
    # Quote anything that is not a plain token: empty, multi-line, or carrying a
    # colon-space / leading special char that a frontmatter reader would split on.
    if "\n" in value or ": " in value or value[0] in "!&*?|>%@`\"'":
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if _SIMPLE_VALUE_RE.match(value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _apply_status(
    text: str,
    *,
    status: str,
    superseded_by: str | None = None,
    reason: str | None = None,
) -> str:
    """Rewrite a page's frontmatter, preserving title/category/created/body."""
    fields, raw, body = parse_frontmatter(text)
    fields["status"] = status
    if superseded_by is not None:
        fields["superseded_by"] = superseded_by
    elif status == SUPERSEDED:
        fields.setdefault("superseded_by", "")
    if reason is not None:
        fields["reason"] = reason
    elif status == WITHDRAWN:
        fields.setdefault("reason", "")

    lines = []
    for key, value in fields.items():
        lines.append(f"{key}: {_fmt_value(value)}")
    new_raw = "\n".join(lines)
    return f"---\n{new_raw}\n---\n{body}"


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else p


def supersede(path: str | Path, by: str, reason: str | None = None) -> Path:
    """Mark a page superseded by another page/URL. Returns the written path."""
    page = _resolve(path)
    if not page.exists():
        raise LifecycleError(f"no such page: {page}")
    if not by or not by.strip():
        raise LifecycleError("supersede requires --by <page-path-or-url>")
    text = page.read_text()
    page.write_text(
        _apply_status(text, status=SUPERSEDED, superseded_by=by, reason=reason)
    )
    return page


def withdraw(path: str | Path, reason: str) -> Path:
    """Mark a page withdrawn (was wrong when written). Returns the written path."""
    page = _resolve(path)
    if not page.exists():
        raise LifecycleError(f"no such page: {page}")
    if not reason or not reason.strip():
        raise LifecycleError("withdraw requires --reason")
    text = page.read_text()
    page.write_text(_apply_status(text, status=WITHDRAWN, reason=reason))
    return page
