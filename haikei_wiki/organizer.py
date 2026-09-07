"""Organizer: the single writer that reconciles the capture inbox into the wiki.

Captures only ever land in <wiki>/inbox/. This pass is the ONLY code that
writes wiki/ pages and index.md (through the existing LLMWikiAdapter). It:

- re-validates every record against the closed capture vocabulary
  (it PROPOSES types from the vocabulary; it never adds new ones),
- writes one page per capture via adapter.write_memory, embedding the
  capture's links as wikilinks in the page content,
- appends a greppable 'organize' entry to log.md,
- moves processed records to inbox/processed/ (rejected to inbox/rejected/).

A lock file in the plugin state dir keeps two organizer passes from running
concurrently, so the graph always has exactly one writer.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .capture import CaptureInbox, log_append, wiki_root
from .adapter import LLMWikiAdapter
from .vocabulary import Vocabulary, VocabularyViolation


class OrganizerError(RuntimeError):
    pass


def state_dir() -> Path:
    d = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if d:
        return Path(d)
    return Path.home() / ".local" / "state" / "herdr" / "plugins" / "haikei.wiki"


class _Lock:
    def __init__(self, path: Path, stale_after: float = 300.0):
        self.path = path
        self.stale_after = stale_after
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(
                    str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
                )
                os.write(fd, f"pid={os.getpid()} ts={time.time()}\n".encode())
                os.close(fd)
                self.acquired = True
                return
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    break
                if age < self.stale_after:
                    raise OrganizerError(
                        f"another organizer holds {self.path} (age {age:.0f}s); "
                        "the graph allows exactly one writer"
                    )
                # Stale lock: remove and retry once.
                self.path.unlink(missing_ok=True)
        raise OrganizerError(f"could not acquire organizer lock {self.path}")

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


@dataclass
class OrganizeResult:
    organized: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _safe_title(title: str) -> str:
    safe = "".join(c if c.isalnum() or c in "- " else "_" for c in title)
    return safe.lower().replace(" ", "-")


def organize(
    wiki_path: Path | None = None,
    vocab: Vocabulary | None = None,
    lock_path: Path | None = None,
) -> OrganizeResult:
    from .vocabulary import load_vocabulary

    if vocab is None:
        vocab = load_vocabulary()

    inbox = CaptureInbox(wiki_path)
    lock = _Lock(lock_path or (state_dir() / "organize.lock"))
    lock.acquire()
    try:
        return _organize_locked(inbox, vocab)
    finally:
        lock.release()


def _organize_locked(inbox: CaptureInbox, vocab: Vocabulary) -> OrganizeResult:
    adapter = LLMWikiAdapter(inbox.wiki_path)
    result = OrganizeResult()
    processed_dir = inbox.inbox_dir / "processed"
    rejected_dir = inbox.inbox_dir / "rejected"

    for path in inbox.pending():
        try:
            record = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            result.rejected.append((str(path), f"unreadable record: {e}"))
            _move(path, rejected_dir, path.name)
            continue

        try:
            vocab.check_capture(record.get("entity_type", ""), record.get("links", []))
        except VocabularyViolation as e:
            result.rejected.append((str(path), str(e)))
            _move(path, rejected_dir, path.name)
            continue

        title = record["title"]
        entity_type = record["entity_type"]
        content = record["content"]
        links = record.get("links", [])

        page_content = content
        if links:
            link_lines = "\n".join(
                f"- {l['predicate']}: [[{l['target']}]]" for l in links
            )
            page_content = f"{content}\n\n## Links\n\n{link_lines}\n"

        page_path = adapter.write_memory(
            page_content, {"title": title, "category": entity_type}
        )
        rel = Path(page_path).relative_to(inbox.wiki_path).as_posix()
        date = datetime.now().strftime("%Y-%m-%d")
        log_append(inbox.log_file, f"\n## [{date}] organize | {title} -> {rel}")
        _move(path, processed_dir, path.name)
        result.organized.append((str(path), rel))
    return result


def _move(src: Path, dest_dir: Path, name: str) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{n}-{name}"
        n += 1
    os.replace(src, dest)
