"""Hybrid search index: FTS5 (BM25) + optional semantic embeddings.

Issue #12: agents search in natural language with words that may not appear
in the record ("worker claim" vs "blocker", "Terraform" vs "tf-apply"). They
need ranked, fuzzy and semantic retrieval, not boolean term matching.

Design:
- **Lexical layer** — SQLite FTS5 (BM25) over title+content of every wiki
  page and pending inbox record, stored under `<wiki>/.index/search.db`.
  If FTS5 is not compiled into the local libsqlite, we fall back to the
  pure-Python token scorer in `textsearch` (no external server needed).
- **Semantic layer** — an embedding per record from a pluggable provider.
  The default provider is offline-null: semantic mode then degrades
  gracefully to lexical (works offline, which is a hard requirement).
  Setting WIKI_EMBED_MODEL (and optionally WIKI_EMBED_URL) enables an
  OpenAI-compatible /api/embeddings provider over HTTP (e.g. a local
  Ollama / llama.cpp tailnet endpoint). Embeddings are stored as float32
  blobs in the same database.
- **Hybrid ranking** — reciprocal rank fusion (RRF) of the lexical and the
  semantic ranking. Hybrid is the default mode; lexical-only always works.

Indexing is incremental: `capture` indexes the inbox record immediately,
`organize` re-indexes moved pages and removes processed/rejected/deleted
records. No full rebuild per query.
"""

import json
import math
import os
import sqlite3
import struct
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .textsearch import score_document

RRF_K = 60


class IndexUnavailable(RuntimeError):
    """The local search index could not be opened or is disabled."""


@dataclass
class IndexedDoc:
    path: str
    kind: str  # "page" | "inbox"
    title: str
    category: str  # frontmatter category (pages) / entity_type (inbox)
    content: str
    mtime: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    path     TEXT PRIMARY KEY,
    kind     TEXT NOT NULL,
    title    TEXT NOT NULL,
    category TEXT NOT NULL,
    content  TEXT NOT NULL,
    mtime    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    path       TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    vector     BLOB NOT NULL
);
"""


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    return conn


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
        return True
    except Exception:
        return False


def _fts_table(conn) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5("
        "path UNINDEXED, title, content)"
    )


def _fts_query(q_tokens: list[str]) -> str:
    # each token as a prefix match: 'worker*'
    return " OR ".join(f'"{t}"*' for t in q_tokens if t)


# --------------------------------------------------------------------------
# embedding providers
# --------------------------------------------------------------------------


class EmbedderUnavailable(RuntimeError):
    pass


class NullEmbedder:
    """Offline default: no semantic index available."""

    model = "none"

    def embed(self, text: str) -> list[float]:
        raise EmbedderUnavailable("no embedding provider configured")


class OllamaCompatEmbedder:
    """OpenAI-compatible /api/embeddings client (Ollama, llama.cpp, vLLM)."""

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 5.0):
        self.model = model
        self.base_url = (
            base_url or os.environ.get("WIKI_EMBED_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.timeout = timeout
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        key = text[:512]
        if key in self._cache:
            return self._cache[key]
        payload = json.dumps({"model": self.model, "prompt": text[:512]}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode())
        vec = data.get("embedding") or (data.get("data") or [{}])[0].get("embedding")
        if not vec:
            raise EmbedderUnavailable(
                f"provider returned no embedding for {self.model}"
            )
        self._cache[key] = [float(x) for x in vec]
        return self._cache[key]


def default_embedder() -> object:
    model = os.environ.get("WIKI_EMBED_MODEL")
    if model:
        return OllamaCompatEmbedder(model)
    return NullEmbedder()


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# --------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------


class SearchIndex:
    """Local hybrid search index over wiki pages and inbox records."""

    def __init__(self, wiki_path: Path, embedder=None):
        self.wiki_path = Path(wiki_path)
        self.db_path = self.wiki_path / ".index" / "search.db"
        self.fts_ok = _fts5_available()
        self.conn = None
        if self.fts_ok:
            self.conn = _open_db(self.db_path)
            _fts_table(self.conn)
            self.conn.commit()
        if embedder is None:
            embedder = default_embedder()
        self.embedder = embedder

    # -- population --------------------------------------------------------

    def upsert(
        self,
        path_str: str,
        kind: str,
        title: str,
        category: str,
        content: str,
        mtime: float,
    ) -> None:
        """Index one document (and its embedding when a provider is set)."""
        if not self.fts_ok:
            return
        assert self.conn is not None
        self.conn.execute(
            "INSERT INTO docs(path, kind, title, category, content, mtime) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "kind=excluded.kind, title=excluded.title, category=excluded.category, "
            "content=excluded.content, mtime=excluded.mtime",
            (path_str, kind, title, category, content, mtime),
        )
        self.conn.execute("DELETE FROM docs_fts WHERE path=?", (path_str,))
        self.conn.execute(
            "INSERT INTO docs_fts(path, title, content) VALUES(?,?,?)",
            (path_str, title, content),
        )
        # keep only embeddings of a live, current model
        self.conn.execute("DELETE FROM embeddings WHERE path=?", (path_str,))
        try:
            vec = self.embedder.embed(f"{title}\n{content[:512]}")
            self.conn.execute(
                "INSERT INTO embeddings(path, model, vector) VALUES(?,?,?)",
                (path_str, self.embedder.model, _pack(vec)),
            )
        except EmbedderUnavailable:
            pass  # offline: lexical-only is fine
        self.conn.commit()

    def remove(self, path_str: str) -> None:
        if not self.fts_ok:
            return
        assert self.conn is not None
        self.conn.execute("DELETE FROM docs WHERE path=?", (path_str,))
        self.conn.execute("DELETE FROM embeddings WHERE path=?", (path_str,))
        self.conn.execute("DELETE FROM docs_fts WHERE path=?", (path_str,))
        self.conn.commit()

    def drop_embeddings(self, keep_model: str | None) -> None:
        """Remove stale embeddings (organisation moves changed old paths)."""
        if not self.fts_ok:
            return
        assert self.conn is not None
        if keep_model is None:
            self.conn.execute("DELETE FROM embeddings")
        else:
            self.conn.execute("DELETE FROM embeddings WHERE model<>?", (keep_model,))
        self.conn.commit()

    def doc_count(self) -> int:
        if not self.fts_ok:
            return 0
        assert self.conn is not None
        return self.conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

    # -- candidate lookups --------------------------------------------------

    def _rows_fts(self, query: str, limit: int) -> list[tuple]:
        assert self.conn is not None
        try:
            return self.conn.execute(
                "SELECT path, bm25(docs_fts) FROM docs_fts WHERE docs_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (_fts_query(query.split()), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # dirty query string: fall out to the token scan below
            return []

    def _rows_scan(self, query: str, limit: int) -> list[tuple]:
        assert self.conn is not None
        rows = self.conn.execute("SELECT path, title, content FROM docs").fetchall()
        scored = []
        for path, title, content in rows:
            s = score_document(query, title, content)
            if s is not None:
                scored.append((path, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _semantic_rows(self, query_vec: list[float], limit: int) -> list[tuple]:
        assert self.conn is not None
        try:
            rows = self.conn.execute(
                "SELECT path, vector FROM embeddings WHERE model=?",
                (self.embedder.model,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        scored = []
        for path, blob in rows:
            sim = _cosine(query_vec, _unpack(blob))
            if sim > 0.05:
                scored.append((path, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    # -- search ---------------------------------------------------------------

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
    ) -> tuple[list[tuple], dict]:
        """Return (results, meta).

        Results: sorted list of (page_path, rrf_score, scores_dict). Meta
        carries the mode that actually ran and per-mode availability.
        """
        meta = {"requested_mode": mode}
        if not self.fts_ok:
            meta["mode"] = "lexical-scan"
            meta["fts5"] = False
            return [
                (p, s, {"lexical": s}) for p, s in self._rows_scan(query, top_k)
            ], meta

        lexical = self._rows_fts(query, top_k * 3)
        if not lexical:
            lexical = self._rows_scan(query, top_k * 3)
        lex_rank = {p: i for i, (p, _) in enumerate(lexical)}
        lex_scores = {p: -s for p, s in lexical}  # bm25 lower is better

        use_sem = mode in ("hybrid", "semantic")
        sem_rank: dict[str, int] = {}
        sem_scores: dict[str, float] = {}
        sem_error = None
        if use_sem:
            try:
                qv = self.embedder.embed(query)
                sem = self._semantic_rows(qv, top_k * 3)
                sem_rank = {p: i for i, (p, _) in enumerate(sem)}
                sem_scores = {p: s for p, s in sem}
            except EmbedderUnavailable as e:
                sem_error = str(e)

        if mode == "semantic" and sem_error and not sem_rank:
            # graceful degrade: offline → lexical
            mode = "lexical"
            meta["semantic_degraded"] = sem_error

        if mode == "semantic" and not sem_rank and not lex_rank:
            meta["mode"] = mode
            return [], meta

        fused: dict[str, dict] = {}
        for p in set(lex_rank) | set(sem_rank):
            entry: dict = {}
            if p in lex_rank:
                entry["lexical"] = round(lex_scores[p], 3)
            if p in sem_scores:
                entry["semantic"] = round(sem_scores[p], 3)
            score = 0.0
            if p in lex_rank:
                score += 1.0 / (RRF_K + lex_rank[p])
            if p in sem_rank:
                score += 1.0 / (RRF_K + sem_rank[p])
            entry["rrf"] = round(score, 6)
            fused[p] = entry

        if mode == "semantic":
            order = sorted(fused.items(), key=lambda kv: sem_rank.get(kv[0], 10**6))
            meta["mode"] = "semantic"
        elif mode == "lexical" and not sem_rank:
            order = sorted(fused.items(), key=lambda kv: lex_rank.get(kv[0], 10**6))
            meta["mode"] = "lexical"
        elif mode == "lexical":
            order = sorted(fused.items(), key=lambda kv: lex_rank.get(kv[0], 10**6))
            meta["mode"] = "lexical"
        else:
            order = sorted(fused.items(), key=lambda kv: kv[1]["rrf"], reverse=True)
            meta["mode"] = "hybrid"
            meta["semantic"] = bool(sem_rank) or sem_error is None
            if sem_error:
                meta["semantic_available"] = False
                meta["semantic_error"] = sem_error

        out = []
        for p, entry in order[:top_k]:
            entry["mode"] = meta["mode"]
            out.append((p, entry.get("rrf", 0.0), entry))
        return out, meta


def parse_since(spec: str) -> float | None:
    """`--since 24h|7d|2026-10-01T15:00` → unix timestamp, or None."""
    spec = spec.strip().lower()
    try:
        if spec.endswith("h"):
            return time.time() - float(spec[:-1]) * 3600
        if spec.endswith("d"):
            return time.time() - float(spec[:-1]) * 86400
        dt = datetime.fromisoformat(spec)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def get_index(wiki_path: Path, embedder=None) -> SearchIndex:
    """Open (best-effort) the SearchIndex; returns None when unavailable."""
    try:
        return SearchIndex(wiki_path, embedder)
    except IndexUnavailable:
        return None


def index_capture_record(wiki_path: Path, record_path: Path) -> None:
    """Index one freshly captured inbox record (best effort, never fatal)."""
    try:
        index = get_index(wiki_path)
        if index is None:
            return
        index_inbox_file(index, record_path, wiki_path)
        return
    except Exception:
        return


def index_organized_pages(wiki_path: Path, pairs: list) -> None:
    """After organize: index new pages, drop inbox records that were filed."""
    try:
        index = get_index(wiki_path)
        if index is None:
            return
        for _src, rel in pairs:
            p = Path(wiki_path) / rel
            if p.is_file():
                index_page_file(index, p, wiki_path)
    except Exception:
        return


def index_removed(wiki_path: Path, path_str: str) -> None:
    """Drop a document (moved inbox record, deleted page) from the index."""
    try:
        index = get_index(wiki_path)
        if index is None:
            return
        index.remove(path_str)
    except Exception:
        return


def index_page_file(index: SearchIndex, path: Path, wiki_root: Path) -> None:
    """Best-effort incremental index of one settled wiki page."""
    try:
        text = path.read_text()
    except OSError:
        return
    title = path.stem
    category = path.parent.name
    if text.startswith("---"):
        block, _, rest = text[3:].partition("---")
        for line in block.splitlines():
            if line.startswith("title:"):
                title = line.partition(":")[2].strip()
            elif line.startswith("category:"):
                category = line.partition(":")[2].strip()
        text = rest
    index.upsert(
        path.relative_to(wiki_root).as_posix(),
        "page",
        title,
        category,
        text,
        path.stat().st_mtime,
    )


def index_inbox_file(index: SearchIndex, path: Path, wiki_root: Path) -> None:
    """Best-effort incremental index of one pending inbox record."""
    try:
        record = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    index.upsert(
        f"inbox:{record.get('id', path.stem)}",
        "inbox",
        str(record.get("title", "")),
        str(record.get("entity_type", "")),
        str(record.get("content", "")),
        path.stat().st_mtime,
    )
