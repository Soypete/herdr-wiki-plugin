"""
LLMWiki Adapter - implements MemorySystem protocol.

Vendored copy of the LLMWiki storage layer so this plugin is self-contained
and installable on its own. Based on Karpathy's LLM-Wiki pattern:
- Raw sources (immutable)
- Wiki (LLM-maintained markdown)
- Schema (AGENTS.md style instructions)
"""

import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

try:
    import watchdog
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
    _FSHandlerBase = watchdog.events.FileSystemEventHandler
except ImportError:
    WATCHDOG_AVAILABLE = False

    class _FSHandlerBase:  # pragma: no cover - only used when watchdog is present
        pass


from .interfaces import (
    MemoryResult,
    MemoryItem,
    Link,
    PathExplanation,
    SystemStats,
)


class LLMWiki:
    """
    LLMWiki - Markdown-based wiki with LLM maintenance.

    Based on Karpathy's pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

    Three layers:
    - raw/          : Immutable source documents (read-only)
    - wiki/         : LLM-generated markdown files (LLM writes, humans read)
    - AGENTS.md     : Schema/instructions for the LLM

    Two index files:
    - index.md      : Content-oriented catalog (organized by category)
    - log.md        : Chronological append-only record of operations

    View in Obsidian for best experience (graph view, dataview, etc.)
    """

    def __init__(
        self,
        wiki_path: Path,
    ):
        """
        Initialize LLMWiki.

        Args:
            wiki_path: Path to the wiki root directory
                       Expected structure:
                       wiki_path/
                       ├── raw/           # Immutable sources
                       ├── wiki/          # LLM-maintained pages
                       ├── index.md       # Content catalog
                       ├── log.md         # Chronological log
                       └── AGENTS.md      # Schema/instructions
        """
        self.wiki_path = Path(wiki_path)
        self.raw_path = self.wiki_path / "raw"
        self.wiki_dir = self.wiki_path / "wiki"
        self.index_file = self.wiki_path / "index.md"
        self.log_file = self.wiki_path / "log.md"
        self.schema_file = self.wiki_path / "AGENTS.md"
        self.inbox_dir = self.wiki_path / "inbox"

        # Ensure structure exists
        self.raw_path.mkdir(parents=True, exist_ok=True)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)

        # Initialize index.md if not exists
        if not self.index_file.exists():
            self.index_file.write_text("# Wiki Index\n\n## Categories\n")

        # Initialize log.md if not exists
        if not self.log_file.exists():
            self.log_file.write_text("# Wiki Log\n\n## Chronological Record\n")

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search wiki using grep and index.md.
        """
        results = []

        # Search index.md
        if self.index_file.exists():
            content = self.index_file.read_text()
            if query.lower() in content.lower():
                results.append(
                    {
                        "file": "index.md",
                        "path": str(self.index_file),
                        "content": content,
                        "score": 0.3,
                    }
                )

        # Grep through wiki files
        if self.wiki_dir.exists():
            try:
                grep_result = subprocess.run(
                    ["grep", "-r", "-l", "-i", query, str(self.wiki_dir)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for match in grep_result.stdout.strip().split("\n"):
                    if match and Path(match).exists():
                        content = Path(match).read_text()
                        # Simple scoring: title match > content match
                        filename = Path(match).stem.lower()
                        score = 0.9 if filename in query.lower() else 0.6

                        results.append(
                            {
                                "file": Path(match).name,
                                "path": match,
                                "content": content[:1000],
                                "score": score,
                            }
                        )
            except Exception:
                pass

        # Sort by score and limit
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_inbox(self, query: str) -> list[dict]:
        """Search pending inbox records by title and content.

        Read-only: never organizes, moves, or mutates inbox records; the
        organizer remains the only writer to the graph. Malformed or
        unreadable JSON records are skipped, not fatal.
        """
        results = []
        if not self.inbox_dir.exists():
            return results

        q = query.lower()
        for path in self.inbox_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            title = str(record.get("title", ""))
            content = str(record.get("content", ""))
            if q in title.lower():
                score = 0.9
            elif q in content.lower():
                score = 0.6
            else:
                continue

            # "inbox:" prefix + source mark the record as pending/unorganized
            # so an agent can tell it from a settled wiki page.
            results.append(
                {
                    "file": "inbox",
                    "path": f"inbox:{record.get('id', path.stem)}",
                    "content": f"[inbox] {title}\n{content}",
                    "score": score,
                }
            )
        return results

    def write(self, title: str, content: str, category: str = "general") -> str:
        """
        Write a new wiki page.

        Args:
            title: Page title
            content: Page content (markdown)
            category: Category/folder for organization

        Returns: path to created file
        """
        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in "- " else "_" for c in title)
        safe_title = safe_title.lower().replace(" ", "-")

        category_dir = self.wiki_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        file_path = category_dir / f"{safe_title}.md"

        # Add frontmatter
        full_content = f"""---
title: {title}
category: {category}
created: {datetime.now().isoformat()}
---

{content}
"""

        file_path.write_text(full_content)

        # Update index
        self._update_index(category, title, safe_title)

        # Log operation
        self._log_operation("write", f"{title} -> {category}/{safe_title}.md")

        return str(file_path)

    def _update_index(self, category: str, title: str, safe_title: str):
        """Update index.md with new entry."""
        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()

        # Check if entry exists
        link = f"- [[{category}/{safe_title}|{title}]]"
        if link not in index_content:
            # Add to appropriate category section
            category_header = f"## {category.title()}"
            if category_header in index_content:
                index_content = index_content.replace(
                    category_header, f"{category_header}\n{link}"
                )
            else:
                index_content += f"\n{category_header}\n{link}\n"

            self.index_file.write_text(index_content)

    def _log_operation(self, operation: str, details: str):
        """Append entry to log.md"""
        from datetime import datetime

        log_content = ""
        if self.log_file.exists():
            log_content = self.log_file.read_text()

        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"\n## [{timestamp}] {operation} | {details}"

        log_content += entry
        self.log_file.write_text(log_content)

    def read(self, path_or_title: str) -> Optional[str]:
        """Read a wiki page by path or title."""
        # Try as path first
        p = Path(path_or_title)
        if p.exists():
            return p.read_text()

        # Try as title in wiki dir
        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.stem.lower() == path_or_title.lower().replace(" ", "-"):
                return md_file.read_text()

        return None

    def get_stats(self) -> dict:
        """Get wiki statistics."""
        total_files = 0
        total_size = 0

        if self.wiki_dir.exists():
            for f in self.wiki_dir.rglob("*.md"):
                total_files += 1
                total_size += f.stat().st_size

        return {
            "total_pages": total_files,
            "total_size_bytes": total_size,
            "path": str(self.wiki_path),
        }


class LLMWikiAdapter:
    """Adapter implementing MemorySystem protocol."""

    def __init__(
        self,
        wiki_path: Path,
        schema_path: Optional[Path] = None,
        raw_sources_path: Optional[Path] = None,
    ):
        self.wiki = LLMWiki(wiki_path)
        self.schema_path = schema_path
        self.raw_sources_path = raw_sources_path or wiki_path / "raw"

    def search_memory(
        self,
        query: str,
        scope: str = "all",
        top_k: int = 10,
        include_inbox: bool = True,
    ) -> list[MemoryResult]:
        """Search wiki pages (index.md + wiki/) and, by default, pending inbox."""
        results = self.wiki.search(query, top_k)
        if include_inbox:
            results = results + self.wiki.search_inbox(query)

        # Same scoring scale for both sources; merged results sort by score.
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:top_k]

        memory_results = []
        for r in results:
            memory_results.append(
                MemoryResult(
                    id=r["path"],
                    content=r["content"],
                    score=r["score"],
                    source=r["file"],
                    created_at=datetime.now(),
                )
            )

        return memory_results

    def read_memory(self, id: str) -> Optional[MemoryItem]:
        """Read a wiki page by filename."""
        content = self.wiki.read(id)
        if content:
            return MemoryItem(
                id=id,
                content=content,
                metadata={"source": id},
                links=[],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        return None

    def explain_path(self, query_or_id: str) -> PathExplanation:
        """Explain how wiki navigation arrived at result."""
        return PathExplanation(
            query=query_or_id,
            steps=[],
            total_hops=0,
            confidence=0.0,
        )

    def write_memory(
        self,
        input: str,
        metadata: dict,
    ) -> str:
        """Write new content to wiki."""
        title = metadata.get("title", "Untitled")
        category = metadata.get("category", "general")

        return self.wiki.write(title, input, category)

    def link_memory(
        self,
        source_id: str,
        target_id: str,
        relation: str,
    ) -> bool:
        """Create link between wiki pages (markdown links)."""
        # Add wikilink to source page
        content = self.wiki.read(source_id)
        if content:
            link = f"[[{target_id}]]"
            if link not in content:
                content += f"\n\nSee also: {link}"
                self.wiki.write(source_id, content, "general")
                return True
        return False

    def get_stats(self) -> SystemStats:
        """Get wiki statistics."""
        stats = self.wiki.get_stats()

        return SystemStats(
            total_items=stats["total_pages"],
            total_links=0,
            wings=0,
            rooms=0,
            drawers=stats["total_pages"],
            storage_size_bytes=stats["total_size_bytes"],
        )

    def ingest_source(self, source_path: Path) -> list[str]:
        """
        Ingest a new source into the wiki.

        Copy raw source and create wiki page summary.
        """
        if not source_path.exists():
            return []

        # Copy to raw
        dest_raw = self.raw_path / source_path.name
        import shutil

        shutil.copy2(source_path, dest_raw)

        # Create wiki page
        content = source_path.read_text()[:5000]  # Limit for now
        page_path = self.wiki.write(
            title=source_path.stem,
            content=f"# {source_path.name}\n\nImported from: {source_path}\n\n```\n{content}\n```",
            category="imported",
        )

        return [page_path]

    def lint_wiki(self) -> dict:
        """
        Health-check the wiki.

        Operations from Karpathy prompt:
        - Look for contradictions between pages
        - Find stale claims superseded by newer sources
        - Find orphan pages with no inbound links
        - Find concepts mentioned but lacking pages
        - Identify missing cross-references
        - Identify data gaps fillable via web search
        """
        from datetime import datetime

        orphans = []
        all_links = set()
        all_pages = []

        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file == self.index_file:
                continue

            content = md_file.read_text()
            all_pages.append(md_file)

            # Extract wikilinks [[category/page|display]]
            import re

            links = re.findall(r"\[\[([^\]|]+)\|?[^\]]*\]\]", content)
            all_links.update(links)

            if "[[" not in content:
                orphans.append(str(md_file))

        # Check for unlinked concepts (pages that exist but aren't linked)
        unlinked = []
        for page in all_pages:
            rel_path = page.relative_to(self.wiki_dir).stem
            category = page.parent.name if page.parent != self.wiki_dir else "general"
            full_ref = f"{category}/{rel_path}"
            if full_ref not in all_links and str(page) not in all_links:
                unlinked.append(str(page))

        # Log the lint operation
        self._log_operation(
            "lint", f"Found {len(orphans)} orphans, {len(unlinked)} unlinked pages"
        )

        return {
            "contradictions": [],
            "stale": [],
            "orphans": orphans,
            "unlinked_pages": unlinked,
            "gaps": [],
        }

    def start_watcher(
        self, watch_path: Optional[Path] = None, on_change: Optional[Callable] = None
    ):
        """Start watching a directory for changes."""
        watcher = LLMWikiWatcher(self.wiki, on_change)
        watcher.start(watch_path)
        return watcher


class WikiFileHandler(_FSHandlerBase):
    """Handler for wiki file system events."""

    def __init__(
        self,
        wiki,
        on_change: Optional[Callable] = None,
        exclude_paths: Optional[list[Path]] = None,
    ):
        super().__init__()
        self.wiki = wiki
        self.on_change = on_change
        self.exclude_paths = exclude_paths or []
        self._seen = set()

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored (is in excluded directory)."""
        path_str = str(path)
        for exclude in self.exclude_paths:
            if path_str.startswith(str(exclude)):
                return True
        return False

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_ignore(path):
            return
        if path.suffix in {".md", ".txt", ".py", ".js", ".ts", ".go", ".rs"}:
            if str(path) not in self._seen:
                self._seen.add(str(path))
                self._handle_file(path, "created")

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_ignore(path):
            return
        if path.suffix in {".md", ".txt", ".py", ".js", ".ts", ".go", ".rs"}:
            self._handle_file(path, "modified")

    def _handle_file(self, path: Path, event_type: str):
        """Handle file change - copy to raw and create wiki page."""
        try:
            if not path.exists():
                return

            # Copy to raw/
            dest_raw = self.wiki.raw_path / path.name
            import shutil

            shutil.copy2(path, dest_raw)

            # Create wiki page
            content = path.read_text()[:5000]
            category = self._detect_category(path)
            page_path = self.wiki.write(
                title=path.stem,
                content=f"# {path.name}\n\nImported from: {path}\n\n```\n{content}\n```",
                category=category,
            )

            self.wiki._log_operation(
                "watch", f"{event_type}: {path.name} -> {category}"
            )

            if self.on_change:
                self.on_change(path, event_type, page_path)

        except Exception as e:
            print(f"Watch error: {e}")

    def _detect_category(self, path: Path) -> str:
        """Detect category from file path."""
        path_str = str(path).lower()
        if "doc" in path_str or "design" in path_str:
            return "docs"
        if "test" in path_str:
            return "tests"
        if "note" in path_str:
            return "notes"
        return "imported"


class LLMWikiWatcher:
    """Wrapper for running wiki watch mode."""

    def __init__(self, wiki, on_change: Optional[Callable] = None):
        self.wiki = wiki
        self.on_change = on_change
        self._observer = None
        self._handler = None
        self._exclude_paths = []

    def start(
        self,
        watch_path: Optional[Path] = None,
        exclude_paths: Optional[list[Path]] = None,
    ):
        """Start watching for file changes."""
        if not WATCHDOG_AVAILABLE:
            raise RuntimeError("watchdog not installed: pip install watchdog")

        target_path = watch_path or self.wiki.raw_path
        target_path.mkdir(parents=True, exist_ok=True)

        self._exclude_paths = [self.wiki.wiki_path, self.wiki.raw_path]
        if exclude_paths:
            self._exclude_paths.extend(exclude_paths)

        self._handler = WikiFileHandler(self.wiki, self.on_change, self._exclude_paths)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(target_path), recursive=True)
        self._observer.start()
        self.wiki._log_operation("watch", f"Started watching: {target_path}")

    def stop(self):
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self.wiki._log_operation("watch", "Stopped watching")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
