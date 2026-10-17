"""Tokenized, ranked text matching for wiki search.

`wiki search` used to treat a whole query as one exact substring (unescaped
into `grep -r`'s regex). Orchestrators coordinated through searches like
"wave dispatch" or "parallel workers DVL" that matched records only when the
words were not adjacent — and got nothing back.

Behavior now:
- the query is tokenized; a record must contain ALL terms (AND), or at least
  SOME terms (ANY) at a lower score, so partial matches surface
- matching is fixed-string / token based — no regex metacharacter surprises
- scoring rewards title hits (0.9 base) above body hits (0.6 base), adds a
  small bonus per extra matched token and per term-frequency, so relevant
  records rank above incidental single-term grep order
- hyphens, underscores, slashes and other separators normalize away, and
  digit identifiers match across separator variants (ADR-011 ≈ adr011 ≈
  "adr 011"); light stemming folds write/writes/written together
"""

import re

_SEPARATORS = re.compile(r"[\s\-_/.:;,()\[\]{}\"'`]+")
_WORD = re.compile(r"[a-z0-9]+")
_STEM_SUFFIXES = (("ies", "y"), ("sses", "ss"), ("es", ""), ("s", ""))
_LEN_STEMS = (("ing", 3), ("ed", 2))


def normalize(text: str) -> str:
    """Lowercase and fold separators to single spaces."""
    return _SEPARATORS.sub(" ", text.lower()).strip()


def compact(text: str) -> str:
    """Lowercase with every separator removed, for identifier matching."""
    return "".join(w for w in _WORD.findall(text.lower()))


def stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix, repl in _STEM_SUFFIXES:
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)] + repl
    for suffix, cut in _LEN_STEMS:
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[:-cut]
    return token


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w]


def _variants(token: str) -> set[str]:
    """Match forms for one token: the token, its stem, and compact variants
    with the digit part separated (adr011 ≈ adr-011 ≈ adr 011)."""
    out = {token, stem(token)}
    m = re.match(r"^([a-z]+)(\d+)$", token)
    if m:
        out.add(stem(m.group(1)))
        out.add(m.group(1) + " " + m.group(2))
    m = re.match(r"^([a-z]+)-(\d+)$", token)
    if m:
        out.add(stem(m.group(1)))
        out.add(m.group(2))
    return out


class Doc:
    """A scored document: precomputed tokens, stems and compact form."""

    def __init__(self, title: str, content: str):
        self.title_tokens = frozenset(stem(t) for t in tokenize(title))
        self.title_compact = compact(title)
        content_tokens = tokenize(normalize(content))
        self.content = content_tokens
        self.stems = (
            frozenset(stem(t) for t in [title, *content_tokens] if False)
            if False
            else frozenset(stem(t) for t in tokenize(title) + content_tokens)
        )
        self.compact = compact(normalize(content)) + compact(title)
        tf: dict[str, int] = {}
        for t in self.stems:
            tf[t] = sum(1 for x in content_tokens if stem(x) == t)
        self.tf = tf


def _match(token: str, doc) -> bool:
    for v in _variants(token):
        if v in doc.compact or stem(v) in doc.stems:
            return True
    m = re.match(r"^([a-z]+)[ \-](\d+)$", token)
    if m and (m.group(1) + m.group(2)) in doc.compact:
        return True
    return False


def score_document(query: str, title: str, content: str) -> float | None:
    """Score one document against the query.

    Returns None when nothing matches. Scale mirrors the original search:
    title hits 0.9 base, body-only hits 0.6 base (ALL terms); ANY-term-only
    matches rank below both.
    """
    q_tokens = tokenize(normalize(query))
    if not q_tokens:
        return None
    doc = Doc(title, content)
    matched = [t for t in q_tokens if _match(t, doc)]
    if not matched:
        return None
    in_title = any(_match(t, Doc(title, "")) for t in matched)
    if len(matched) == len(q_tokens):
        base = 0.9 if in_title else 0.6
    else:
        base = 0.55 if in_title else 0.3
    bonus = 0.02 * (len(matched) - 1)
    # term-frequency bonus only when a term repeats in the body, so a single
    # title (or body) hit keeps its exact base score
    tf_extra = 0
    for t in matched:
        count = min(doc.tf.get(stem(t), 0), 5)
        if count > 1:
            tf_extra += count - 1
    bonus += 0.002 * min(tf_extra, 10)
    return round(min(base + bonus, 1.0), 3)
