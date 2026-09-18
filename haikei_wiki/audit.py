"""Audit: scan the wiki for structural issues.

Read-only — never mutates the wiki, the inbox, or the index. Reports:

- orphans: pages with no inbound wikilinks from other wiki pages
- broken_links: wikilinks pointing to non-existent pages
- unindexed: wiki pages not listed in index.md
- empty_pages: pages whose markdown body is only frontmatter or trivially short
- stale_inbox: pending inbox records older than a threshold (default 7 days)
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .capture import wiki_root


@dataclass
class AuditReport:
    orphans: list[str] = field(default_factory=list)
    broken_links: list[tuple[str, str]] = field(default_factory=list)
    unindexed: list[str] = field(default_factory=list)
    empty_pages: list[str] = field(default_factory=list)
    stale_inbox: list[str] = field(default_factory=list)
    total_pages: int = 0
    total_inbox: int = 0
    total_orphans: int = 0
    total_broken_links: int = 0
    total_unindexed: int = 0
    total_empty: int = 0
    total_stale: int = 0


def audit(wiki_path: Optional[Path] = None, stale_days: int = 7) -> AuditReport:
    wiki = Path(wiki_path) if wiki_path else wiki_root()
    wiki_dir = wiki / "wiki"
    index_file = wiki / "index.md"
    inbox_dir = wiki / "inbox"

    report = AuditReport()

    # --- collect all wiki pages ---
    all_pages: list[Path] = []
    if wiki_dir.exists():
        all_pages = sorted(wiki_dir.rglob("*.md"))
    report.total_pages = len(all_pages)

    # --- parse index.md for linked entries ---
    indexed_refs: set[str] = set()
    if index_file.exists():
        for m in re.finditer(r"\[\[([^\]]+)\]\]", index_file.read_text()):
            indexed_refs.add(m.group(1))

    # --- first pass: collect all wikilinks from all pages ---
    page_paths: set[str] = set()
    page_refs: set[str] = set()  # "category/title" refs
    for md in all_pages:
        rel = md.relative_to(wiki).as_posix()
        page_paths.add(str(md))
        page_paths.add(rel)
        # also register as "category/title" ref for wikilink matching
        if md.parent != wiki_dir:
            cat = md.parent.name
            page_refs.add(f"{cat}/{md.stem}")
        page_refs.add(md.stem)

    inbound_links: dict[str, int] = {}
    link_graph: dict[str, list[str]] = {}

    for md in all_pages:
        content = md.read_text()
        rel = md.relative_to(wiki).as_posix()
        links = re.findall(r"\[\[([^\]|]+)\|?[^\]]*\]\]", content)
        resolved = []
        for raw_target in links:
            # wikilinks might be "category/title" or just "title"
            target = raw_target.strip()
            resolved.append(target)
            inbound_links.setdefault(target, 0)
            inbound_links[target] += 1
        link_graph[rel] = resolved

    # --- orphans: pages with no inbound links from other wiki pages ---
    for md in all_pages:
        rel = md.relative_to(wiki).as_posix()
        # determine refs for this page
        cat = md.parent.name if md.parent != wiki_dir else "general"
        refs = [f"{cat}/{md.stem}", md.stem, rel]
        has_inbound = any(inbound_links.get(r, 0) > 0 for r in refs)
        # also check if any other page links to us by full path
        if not has_inbound:
            for src_md in all_pages:
                if src_md == md:
                    continue
                src_content = src_md.read_text()
                if rel in src_content or md.stem in src_content:
                    has_inbound = True
                    break
        if not has_inbound:
            report.orphans.append(rel)
    report.total_orphans = len(report.orphans)

    # --- broken links: wikilinks targeting non-existent pages ---
    handled = set()
    for src_rel, targets in link_graph.items():
        for t in targets:
            key = (src_rel, t)
            if key in handled:
                continue
            handled.add(key)
            t = t.strip()
            exists = False
            if t in page_paths or t in page_refs:
                exists = True
            else:
                check_path = wiki / t
                if check_path.exists() or check_path.with_suffix(".md").exists():
                    exists = True
                else:
                    for md in all_pages:
                        if md.stem == t or md.stem == t.rstrip(".md"):
                            exists = True
                            break
            if not exists:
                report.broken_links.append((src_rel, t))
    report.total_broken_links = len(report.broken_links)

    # --- unindexed: pages not listed in index.md ---
    for md in all_pages:
        rel = md.relative_to(wiki).as_posix()
        cat = md.parent.name if md.parent != wiki_dir else "general"
        ref = f"{cat}/{md.stem}"
        if ref not in indexed_refs and rel not in indexed_refs:
            report.unindexed.append(rel)
    report.total_unindexed = len(report.unindexed)

    # --- empty / trivial pages ---
    for md in all_pages:
        content = md.read_text()
        body = content
        # strip frontmatter
        body = re.sub(r"^---\n.*?\n---\n", "", body, count=1, flags=re.DOTALL)
        body = body.strip()
        if not body or len(body) < 20:
            report.empty_pages.append(md.relative_to(wiki).as_posix())
    report.total_empty = len(report.empty_pages)

    # --- stale inbox records ---
    if inbox_dir.exists():
        now = time.time()
        for f in sorted(inbox_dir.glob("*.json")):
            try:
                age_seconds = now - f.stat().st_mtime
            except OSError:
                continue
            age_days = age_seconds / 86400
            if age_days >= stale_days:
                report.stale_inbox.append(f.name)
        report.total_stale = len(report.stale_inbox)
        report.total_inbox = len(list(inbox_dir.glob("*.json")))

    return report
