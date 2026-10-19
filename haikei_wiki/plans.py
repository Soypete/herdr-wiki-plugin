"""Session plan lifecycle (issue #22).

A wiki `plan` capture is a session-scoped execution plan. This module gives
each plan a lifecycle so a crashed or rate-limited session leaves recoverable
work instead of an orphan:

- **active** — being worked on now
- **completed** — all tasks landed; kept for the record
- **interrupted** — the session ended early (crash/rate limit); unfinished
  work listed in the body is recoverable
- **archived** — superseded or parked; out of the active view

Status lives in the page frontmatter (`status:`, plus `interrupt_reason:`
when interrupted). `takeover` lists active/interrupted plans and any tasks
still open in their bodies — a new session picks a plan up, verifies each
open task against reality, and re-owns it. Nothing is deleted; lifecycle
writes touch only status fields.
"""

from pathlib import Path

from .lifecycle import LifecycleError, _apply_status, parse_frontmatter

ACTIVE = "active"
COMPLETED = "completed"
INTERRUPTED = "interrupted"
ARCHIVED = "archived"
LIFECYCLE = (ACTIVE, COMPLETED, INTERRUPTED, ARCHIVED)


class PlanError(ValueError):
    pass


def _plan_dir(wiki_path: Path) -> Path:
    return Path(wiki_path) / "wiki" / "plan"


def plan_category_pages(wiki_path: Path) -> list[Path]:
    d = _plan_dir(wiki_path)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.md") if p.is_file())


def _page_full_path(page: str | Path, wiki_path: Path) -> Path:
    p = Path(page)
    if p.is_absolute():
        return p
    name = page if str(page).endswith(".md") else f"{page}.md"
    return _plan_dir(wiki_path) / name


def set_status(
    page: str | Path,
    status: str,
    wiki_path: Path,
    reason: str | None = None,
) -> Path:
    """Set one plan lifecycle status in the page frontmatter."""
    if status not in LIFECYCLE:
        raise PlanError(f"bad plan status {status!r} (one of {', '.join(LIFECYCLE)})")
    p = _page_full_path(page, wiki_path)
    if not p.exists():
        raise PlanError(f"no such plan page: {page}")
    text = p.read_text(encoding="utf-8", errors="strict")
    fields, _, _ = parse_frontmatter(text)
    if fields.get("category") != "plan" and p.parent.name != "plan":
        raise PlanError(
            f"{page} is not a plan page (category {fields.get('category')!r})"
        )
    extra: dict[str, str] = {}
    if status == INTERRUPTED:
        if not reason:
            raise PlanError("interrupt requires a reason (crash, rate limit, ...)")
        extra["interrupt_reason"] = reason
    try:
        new_text = _apply_status(
            text,
            status=status,
            reason=reason if status in (COMPLETED, ARCHIVED) else None,
            extra=extra,
        )
    except LifecycleError as e:  # unparseable page
        raise PlanError(str(e)) from e
    p.write_text(new_text, encoding="utf-8")
    return p


def open_tasks(text: str) -> list[str]:
    """Unfinished `- [ ]` task lines from a plan body."""
    import re

    return [
        m.group(1).strip() for m in re.finditer(r"^\s*-\s*\[\s\]\s*(.+)$", text, re.M)
    ]


def takeover(wiki_path: Path) -> list[dict]:
    """Plans a new session can pick up: active/interrupted with open tasks.

    Each entry: {page, status, interrupt_reason, open_tasks}. Completed and
    archived plans are omitted.
    """
    out = []
    now_alive = (ACTIVE, INTERRUPTED)
    for p in plan_category_pages(wiki_path):
        try:
            fields, _, body = parse_frontmatter(
                p.read_text(encoding="utf-8", errors="ignore")
            )
        except (OSError, ValueError):
            continue
        status = str(fields.get("status", "")).strip() or ACTIVE
        if status not in now_alive:
            continue
        out.append(
            {
                "page": p.name,
                "status": status,
                "interrupt_reason": fields.get("interrupt_reason", ""),
                "open_tasks": open_tasks(body),
            }
        )
    return out
