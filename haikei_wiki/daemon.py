"""Scheduled organizer runner + single-writer locking (issue #22).

A launchd job (15-minute cadence) calls `wiki organize --daemon`:

- the graph keeps exactly one writer: the run takes the organizer lock
  (`_Lock`, reuse of `organizer.organize`), skipping cleanly when another
  pass (human or another orchestration tick) holds it,
- every outcome is logged with a timestamp to a run log in the plugin state
  dir (organized/rejected counts, lock skips, failures with the reason),
- errors are reported on stderr with a non-zero exit so launchd surfaces
  them, but contention with a live organizer is a normal skip (exit 0),
- no LLM calls anywhere in the path — capture, vocabulary checks, page
  writes and the index update are all deterministic local steps.
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .organizer import OrganizerError, organize, state_dir
from .vocabulary import load_vocabulary

DEFAULT_INTERVAL_SECONDS = 15 * 60


def log_file_path() -> Path:
    return state_dir() / "organize-daemon.log"


def log_line(message: str, log_path: Path | None = None) -> None:
    path = Path(log_path) if log_path else log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {message}\n")


def run_once(
    wiki_path: Path | None = None,
    log_path: Path | None = None,
    lock_path: Path | None = None,
) -> int:
    """One organize pass under the single-writer lock, logged and reported.

    Returns a process exit code (0 success/skip, 1 organise failure).
    """
    log_path = Path(log_path) if log_path else log_file_path()
    started = time.monotonic()
    try:
        if wiki_path and wiki_path.exists() is False:
            wiki_path = None
        vocab = load_vocabulary()
        result = organize(wiki_path=wiki_path, vocab=vocab, lock_path=lock_path)
    except OrganizerError as e:
        message = str(e)
        if "holds" in message:
            # normal contention with a live writer: skip, not fail
            log_line(f"skip: {message}", log_path)
            print(f"organize skipped: {message}", file=sys.stderr)
            return 0
        log_line(f"error: {message}", log_path)
        print(f"organize failed: {message}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - the runner must report, not die silently
        log_line(f"error: unexpected {type(e).__name__}: {e}", log_path)
        print(f"organize failed unexpectedly: {e}", file=sys.stderr)
        return 1

    took = time.monotonic() - started
    log_line(
        f"ok: organized={len(result.organized)} rejected={len(result.rejected)} "
        f"took={took:.1f}s",
        log_path,
    )
    if result.organized or result.rejected:
        for src, rel in result.organized:
            log_line(f"  {src} -> {rel}", log_path)
        for src, reason in result.rejected:
            log_line(f"  rejected {src}: {reason}", log_path)
    return 0


def loop(
    interval: float = DEFAULT_INTERVAL_SECONDS,
    wiki_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    """Continuous runner (for --interval mode / long-lived installs)."""
    while True:
        run_once(wiki_path, log_path)
        time.sleep(interval)
