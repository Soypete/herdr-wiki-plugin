"""Capture inbox: single-writer discipline for concurrent agents.

Multiple agents capture concurrently. Concurrent writes to interlinked
markdown corrupt link structure, so a capture NEVER touches wiki/ pages or
index.md. It only:

1. validates against the closed capture vocabulary (write boundary),
2. atomically creates one inbox file per capture (O_EXCL, unique name),
3. appends one greppable line to log.md with a single O_APPEND write
   (append-only, safe under concurrency; log.md is not the graph).

A separate organizer pass (organizer.py) is the only writer to the graph.
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .context import Provenance
from .vocabulary import Vocabulary, VocabularyViolation


class CaptureError(ValueError):
    pass


@dataclass
class Capture:
    title: str
    entity_type: str
    content: str
    links: list[dict] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    id: str = field(
        default_factory=lambda: (
            datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
        )
    )
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_record(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "entity_type": self.entity_type,
            "content": self.content,
            "links": self.links,
            "provenance": self.provenance.as_dict(),
            "created_at": self.created_at,
        }


def wiki_root() -> Path:
    env = os.environ.get("WIKI_PATH")
    return Path(env) if env else Path.home() / "code" / "wiki"


def log_append(log_file: Path, entry: str) -> None:
    """Append one entry to log.md with a single O_APPEND write.

    Matches the existing log.md convention: '## [YYYY-MM-DD] op | details'.
    One write() call per entry keeps concurrent appends from interleaving.
    """
    data = entry.encode("utf-8")
    fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


class CaptureInbox:
    """One file per capture, atomically created, under <wiki>/inbox/."""

    def __init__(self, wiki_path: Path | None = None):
        self.wiki_path = Path(wiki_path) if wiki_path else wiki_root()
        self.inbox_dir = self.wiki_path / "inbox"
        self.log_file = self.wiki_path / "log.md"

    def write(self, capture: Capture, vocab: Vocabulary) -> Path:
        """Validate at the write boundary and land the capture in the inbox.

        Raises VocabularyViolation on any out-of-vocabulary type or
        predicate. Nothing is normalized or coerced.
        """
        vocab.check_capture(capture.entity_type, capture.links)
        if not capture.title.strip():
            raise CaptureError("capture title must be non-empty")
        if not capture.content.strip():
            raise CaptureError("capture content must be non-empty")

        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        record = capture.to_record()
        payload = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )

        # Atomic create: O_EXCL with a unique name. Retry on the (practically
        # impossible) collision with a fresh id.
        for _ in range(5):
            path = self.inbox_dir / f"{capture.id}.json"
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                break
            except FileExistsError:
                capture.id = (
                    datetime.now().strftime("%Y%m%dT%H%M%S%f")
                    + "-"
                    + uuid.uuid4().hex[:8]
                )
                record = capture.to_record()
                payload = (
                    json.dumps(record, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
        else:
            raise CaptureError(
                f"could not allocate a unique inbox name under {self.inbox_dir}"
            )

        try:
            os.write(fd, payload)
        finally:
            os.close(fd)

        date = datetime.now().strftime("%Y-%m-%d")
        log_append(self.log_file, f"\n## [{date}] capture | {capture.title}")
        return path

    def pending(self) -> list[Path]:
        if not self.inbox_dir.exists():
            return []
        return sorted(p for p in self.inbox_dir.glob("*.json"))
