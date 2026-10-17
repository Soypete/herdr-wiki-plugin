"""`wiki show` — print a full page or inbox record.

Agents get whole pages through the CLI so they never have to read wiki files
with a file tool (which triggers external-directory permission prompts for
opencode workers in scratch worktrees).

Accepts:
- what `wiki search` prints (an absolute or wiki-relative page path,
  with or without the `.md` suffix, e.g. `wiki/decision/foo.md`,
  `decision/foo` or `wiki/decision/foo`)
- bare page-name shorthands (`foo`)
- inbox record ids (`inbox:<id>`, with or without `.json`)
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .capture import wiki_root
from .lifecycle import parse_frontmatter

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


class ShowError(ValueError):
    """The requested page or inbox record could not be resolved or read."""


@dataclass
class ShownPage:
    path: str
    title: str
    category: str
    created: str
    content: str
    links: list[str]

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "category": self.category,
            "created": self.created,
            "content": self.content,
            "links": self.links,
        }


def resolve_page(spec: str, wiki_path: Path | None = None) -> Path:
    """Resolve a page spec to an existing wiki page file."""
    root = Path(wiki_path) if wiki_path else wiki_root()
    spec = spec.strip()
    if not spec:
        raise ShowError("empty page spec")

    candidates = []
    p = Path(spec)
    if p.is_absolute():
        candidates.append(p)
        if p.suffix != ".md":
            candidates.append(p.with_suffix(".md"))
    else:
        rel = spec[5:] if spec.startswith("wiki/") else spec
        # strip a redundant inner "wiki/" like "wiki/wiki/decision/foo.md"
        if rel.startswith("wiki/"):
            rel = rel[5:]
        base = rel[:-3] if rel.endswith(".md") else rel
        # "decision/foo" or "decision/foo/foo.md"
        candidates.append(root / "wiki" / f"{base}.md")
        candidates.append(root / f"{base}.md")
        # page name alone: look in every category
        if "/" not in base:
            if (root / "wiki").exists():
                candidates.extend((root / "wiki").glob(f"*/{base}.md"))

    for cand in candidates:
        if cand.is_file():
            return cand
    raise ShowError(f"no such page: {spec}")


def resolve_inbox(spec: str, wiki_path: Path | None = None) -> Path:
    """Resolve an `inbox:<id>` spec to an existing inbox record file."""
    root = Path(wiki_path) if wiki_path else wiki_root()
    rid = spec[len("inbox:") :].strip() if spec.startswith("inbox:") else spec.strip()
    if rid.startswith("inbox/"):
        rid = rid[6:]
    record = root / "inbox" / (rid if rid.endswith(".json") else f"{rid}.json")
    if record.is_file():
        return record
    raise ShowError(f"no such inbox record: {spec}")


def show_inbox(spec: str, wiki_path: Path | None = None) -> ShownPage:
    record_path = resolve_inbox(spec, wiki_path)
    try:
        record = json.loads(record_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ShowError(f"unreadable inbox record {record_path.name}: {e}") from e
    links = [
        f"{l.get('predicate', '')}:{l.get('target', '')}"
        for l in record.get("links", [])
    ]
    return ShownPage(
        path=f"inbox:{record.get('id', record_path.stem)}",
        title=str(record.get("title", "")),
        category=str(record.get("entity_type", "inbox")),
        created=str(record.get("created_at", "")),
        content=str(record.get("content", "")),
        links=links,
    )


def show(spec: str, wiki_path: Path | None = None) -> ShownPage:
    """Print-ready view of a page or inbox record (full content, no truncation)."""
    root = Path(wiki_path) if wiki_path else wiki_root()
    spec = spec.strip()
    if spec.startswith("inbox:") or not spec:
        return show_inbox(spec, root)
    page = resolve_page(spec, root)
    try:
        text = page.read_text()
    except OSError as e:
        raise ShowError(f"unreadable page {page}: {e}") from e
    fields, _, body = parse_frontmatter(text)
    rel = page.relative_to(root).as_posix() if page.is_relative_to(root) else str(page)
    return ShownPage(
        path=rel,
        title=str(fields.get("title", page.stem)),
        category=str(
            fields.get("category", page.parent.name if page.parent != root else "")
        ),
        created=str(fields.get("created", "")),
        content=text,
        links=_WIKILINK_RE.findall(body),
    )
