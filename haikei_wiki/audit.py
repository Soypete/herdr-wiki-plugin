"""Coordination-graph audit: find pages that no longer describe reality.

Read-only. It reports candidates and never modifies or deletes a page. The wiki
keeps a single-writer discipline: only `organize` writes the graph, and only the
lifecycle commands (`supersede`/`withdraw`) write status fields. `audit` reads.

It audits ONLY the coordination categories (claim, decision, blocker,
contradiction, handoff, ack, contract_change, release, entity, source). It does
not touch imported/, docs/, notes/, or tests/.

Checks, strongest signal first:
  1. dead_citation   - a cited path:line no longer resolves, or the cited range
                       no longer falls within the span of the symbol the page names
  2. dead_branch     - a named git branch is gone from the repo (remote + local + worktrees)
  3. merged_pr       - a page asserts a PR is open/pending, but gh reports it merged/closed
  4. unresolved_claim- a claim older than --stale-days with no later release/handoff on its subject
  5. resolved_blocker- a blocker whose subject appears in a later decision, or whose
                       "Blocks PR N" is now merged/closed
  6. contradicted    - two pages on the same subject reaching different conclusions
                       (NEEDS JUDGMENT only; never ranked high)

`gh` is optional. When it is unavailable or unauthenticated, checks 3 and the
PR half of 5 degrade to a weaker signal (no PR findings) rather than erroring.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

COORDINATION_CATEGORIES = (
    "claim",
    "decision",
    "blocker",
    "contradiction",
    "handoff",
    "ack",
    "contract_change",
    "release",
    "entity",
    "source",
)

CONF_LIKELY = "LIKELY STALE"
CONF_POSSIBLY = "POSSIBLY STALE"
CONF_JUDGMENT = "NEEDS JUDGMENT"

REPO_NAMES = ("kei", "pedro-tag", "pedro-agentware", "kei-agents")

# Map a page-text repo token to its GitHub owner/repo for `gh pr view`.
TOKEN_TO_GH = {
    "kei": "HaikeiLabs/kei",
    "kei-agents": "HaikeiLabs/Kei-Agents",
    "pedro-tag": "HaikeiLabs/Kei-Chat-Harness",
    "pedro-agentware": "HaikeiLabs/Agentware",
}

_DEFAULT_REPO_ROOTS = (
    Path.home() / "code",
    Path.home() / "code" / "haikei",
    Path.home() / "code" / "pedro",
)

_NOISE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    ".pixi",
    "venv",
    "env",
    "dist",
    "build",
    "out",
    "vendor",
    "__pycache__",
    ".next",
}


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    page: str
    category: str
    check: str
    confidence: str
    evidence: str
    related: str = ""

    def to_dict(self):
        d = {
            "page": self.page,
            "category": self.category,
            "check": self.check,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }
        if self.related:
            d["related"] = self.related
        return d


@dataclass
class AuditReport:
    findings: list
    pages_scanned: int
    checks: dict = field(default_factory=dict)

    def by_confidence(self):
        groups = {CONF_LIKELY: [], CONF_POSSIBLY: [], CONF_JUDGMENT: []}
        for f in self.findings:
            groups.setdefault(f.confidence, []).append(f)
        return groups

    def to_dict(self):
        return {
            "pages_scanned": self.pages_scanned,
            "checks": self.checks,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# repo discovery
# ---------------------------------------------------------------------------


def _is_git_repo(p: Path) -> bool:
    dot = p / ".git"
    return dot.is_dir() or dot.is_file()


def discover_repos(extra_dirs=None) -> dict:
    """Map repo name -> local path. Honours WIKI_AUDIT_REPOS (JSON) and
    WIKI_AUDIT_REPO_DIRS (colon-separated), then searches default roots."""
    result = {}
    env_map = os.environ.get("WIKI_AUDIT_REPOS", "")
    if env_map:
        try:
            result = {k: Path(v) for k, v in json.loads(env_map).items()}
        except (ValueError, TypeError):
            result = {}

    roots = []
    if extra_dirs:
        roots += [Path(d) for d in extra_dirs]
    env_dirs = os.environ.get("WIKI_AUDIT_REPO_DIRS", "")
    if env_dirs:
        roots += [Path(d) for d in env_dirs.split(":") if d]
    roots += list(_DEFAULT_REPO_ROOTS)

    for name in REPO_NAMES:
        if name in result:
            continue
        for root in roots:
            cand = root / name
            if cand.is_dir() and _is_git_repo(cand):
                result[name] = cand
                break
    return {k: v for k, v in result.items() if v.exists()}


# ---------------------------------------------------------------------------
# github resolver (optional; degrades to None)
# ---------------------------------------------------------------------------


class GithubResolver:
    def __init__(self, gh_bin="gh", timeout=12):
        self._gh = gh_bin
        self._timeout = timeout
        self._cache = {}

    def pr_state(self, repo: str, number: int):
        """Return 'OPEN', 'MERGED', or 'CLOSED'; None when gh is unavailable
        or the PR cannot be resolved in that repo."""
        key = (repo, number)
        if key in self._cache:
            return self._cache[key]
        state = None
        try:
            out = subprocess.run(
                [
                    self._gh,
                    "pr",
                    "view",
                    str(number),
                    "--repo",
                    repo,
                    "--json",
                    "state",
                ],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if out.returncode == 0:
                data = json.loads(out.stdout)
                state = data.get("state")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            state = None
        self._cache[key] = state
        return state


# ---------------------------------------------------------------------------
# frontmatter / page helpers
# ---------------------------------------------------------------------------


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fields = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        if key.strip():
            fields[key.strip()] = value.strip()
    return fields


def _page_created(path: Path):
    fields = _frontmatter(path.read_text())
    created = fields.get("created", "")
    if created:
        try:
            return datetime.fromisoformat(created)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _rel(wiki_path: Path, path: Path) -> str:
    try:
        return path.relative_to(wiki_path).as_posix()
    except ValueError:
        return str(path)


def _coordination_pages(wiki_path: Path):
    wiki_dir = wiki_path / "wiki"
    pages = []
    if not wiki_dir.is_dir():
        return pages
    for cat in COORDINATION_CATEGORIES:
        d = wiki_dir / cat
        if d.is_dir():
            pages += sorted(d.glob("*.md"))
    return pages


# ---------------------------------------------------------------------------
# citation extraction + resolution (check 1)
# ---------------------------------------------------------------------------

_EXT = r"(?:go|py|ts|tsx|js|jsx|rs|sh|bash|md|markdown|toml|yaml|yml|json|sql)"
_CITE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.%s):(\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*)"
    % _EXT
)
_SYMBOL_IN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s+(?:in|at)\s+\(?(__CITE__)\)?")
_SYMBOL_PAREN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(__CITE__)\s*\)")

_SYMBOL_STOPWORDS = frozenset(
    """the a an in at of to on for and or not is are was were be been it its
    this that these those with from by as file line lines code function method
    handler route path site unset sql http api defect rule task status open new
    old page docs repo work check test tests row table column key value list get
    set create update delete read write return returns uses use call calls called
    now only also so if then than roles role group groups user users workspace
    org orgs tenant select where from into join on when then else do does did
    has have had being been definition pattern logic code check guard seam
    handler route function method call site line file repo work value row
    column table key field argument arg param parameter variable constant
    """.split()
)

_DEF_RE = {
    "go": r"func\s+{s}\b",
    "py": r"def\s+{s}\b",
    "ts": r"(?:export\s+)?(?:async\s+)?function\s+{s}\b|(?:const|let|var)\s+{s}\s*=",
}
_TOPLEVEL = re.compile(
    r"^(func|type|var|const|package|import|def|class|@|export|function|module)\b"
)


def _span(numbers_str: str):
    nums = [int(n) for n in re.findall(r"\d+", numbers_str)]
    return min(nums), max(nums)


def _is_urlish(text: str, start: int) -> bool:
    return "://" in text[max(0, start - 8) : start]


def _symbol_for(cite: str, body: str):
    esc = re.escape(cite)
    m = _SYMBOL_IN.pattern.replace("__CITE__", esc)
    mm = re.search(m, body)
    if mm and mm.group(1).lower() not in _SYMBOL_STOPWORDS:
        return mm.group(1)
    m2 = _SYMBOL_PAREN.pattern.replace("__CITE__", esc)
    mm2 = re.search(m2, body)
    if mm2:
        w = mm2.group(1)
        if w.lower() not in _SYMBOL_STOPWORDS and re.search(r"[A-Z0-9_]", w):
            return w
    return None


def _lang_for(path: Path):
    s = path.suffix.lower()
    if s == ".go":
        return "go"
    if s == ".py":
        return "py"
    if s in (".ts", ".tsx", ".js", ".jsx"):
        return "ts"
    return None


def _def_line(lines, sym):
    """Index of the line that DEFINES sym, or None."""
    for lang, pat in _DEF_RE.items():
        rx = re.compile(pat.format(s=re.escape(sym)))
        for i, line in enumerate(lines):
            if rx.match(line.strip()):
                return i
    return None


def _function_end(lines, def_idx):
    for i in range(def_idx + 1, len(lines)):
        ls = lines[i].strip()
        if _TOPLEVEL.match(ls) or ls == "}":
            return i
    return len(lines)


def _citation_still_valid(file_path: Path, sym: str, lo: int, hi: int, tol: int = 2):
    """True when the cited range [lo,hi] still falls within the span of sym.

    A citation is still valid if the symbol appears inside the range, or if the
    range is the body of the named symbol (its definition starts at or before
    the range and its span covers the range). It is dead only when the symbol
    no longer covers the cited lines.
    """
    try:
        lines = file_path.read_text().splitlines()
    except OSError:
        return False
    n = len(lines)
    if n == 0:
        return False
    sym_rx = re.compile(r"\b" + re.escape(sym) + r"\b")
    occ = [i for i, line in enumerate(lines) if sym_rx.search(line)]
    if not occ:
        return False
    # 1) symbol inside the cited range
    for o in occ:
        if (lo - 1 - tol) <= (o + 1) <= (hi + tol):
            return True
    # 2) range is the body of the named symbol
    d = _def_line(lines, sym)
    if d is not None and (d + 1) <= (lo + tol):
        end = _function_end(lines, d)
        if (hi) <= (end + tol):
            return True
    return False


def _repo_name_tokens(text: str):
    tokens = set()
    low = text.lower()
    if re.search(r"\bkei\b(?!-)", low) or "kei repo" in low:
        tokens.add("kei")
    if re.search(r"\bkei-agents\b", low):
        tokens.add("kei-agents")
    if re.search(r"\bpedro-tag\b|\bpedro tag\b", low):
        tokens.add("pedro-tag")
    if re.search(r"\bpedro-agentware\b|\bagentware\b(?!-)", low):
        tokens.add("pedro-agentware")
    return tokens


def _resolve_file(repos: dict, cite_path: str, page_text: str):
    """Resolve a cited path to (repo_name, file_path) or None.

    Returns a path even when the file is missing, so the caller can flag a
    deleted file. Returns None only when the repo cannot be determined uniquely
    (spec: skip if you cannot).
    """
    cands = []
    for name, root in repos.items():
        if (root / cite_path).is_file():
            cands.append((name, root / cite_path))
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        tok = _repo_name_tokens(page_text)
        narrowed = [c for c in cands if c[0] in tok]
        if len(narrowed) == 1:
            return narrowed[0]
        return None
    if "/" not in cite_path:
        hits = []
        for name, root in repos.items():
            for p in root.rglob(cite_path):
                if any(part in _NOISE_DIRS for part in p.parts):
                    continue
                hits.append((name, p))
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            tok = _repo_name_tokens(page_text)
            narrowed = [h for h in hits if h[0] in tok]
            if len(narrowed) == 1:
                return narrowed[0]
            return None  # ambiguous bare filename -> skip
        # 0 hits: the file is genuinely missing; trust a single named repo
        tok = _repo_name_tokens(page_text)
        if len(tok) == 1:
            name = next(iter(tok))
            return (name, repos[name] / cite_path)
        return None
    # path has a directory but is not found at the repo root: pages often cite
    # paths relative to a subdirectory (e.g. "migrations/002_...sql" for
    # "cmd/abac-engine/migrations/002_...sql"). Try a suffix match.
    suffix = "/" + cite_path
    hits = []
    for name, root in repos.items():
        for p in root.rglob(Path(cite_path).name):
            if any(part in _NOISE_DIRS for part in p.parts):
                continue
            if p.as_posix().endswith(suffix):
                hits.append((name, p))
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        tok = _repo_name_tokens(page_text)
        narrowed = [h for h in hits if h[0] in tok]
        if len(narrowed) == 1:
            return narrowed[0]
        return None
    # no suffix match either: trust a single named repo so a deleted file flags
    tok = _repo_name_tokens(page_text)
    if len(tok) == 1:
        name = next(iter(tok))
        return (name, repos[name] / cite_path)
    return None


def _check_dead_citation(page: Path, text: str, repos: dict):
    findings = []
    body = text
    for m in _CITE_RE.finditer(body):
        cite = m.group(0)
        if _is_urlish(body, m.start()):
            continue
        cite_path = m.group(1)
        lo, hi = _span(m.group(2))
        resolved = _resolve_file(repos, cite_path, text)
        if resolved is None:
            continue
        repo_name, repo_file = resolved
        if not repo_file.exists():
            findings.append(
                Finding(
                    _rel(page.parent.parent.parent, page),
                    page.parent.name,
                    "dead_citation",
                    CONF_LIKELY,
                    f"{cite_path} does not exist in {repo_name}",
                )
            )
            continue
        # The symbol-moved check only applies to a real line range. A single
        # line is too imprecise (off-by-one is common) and would be noisy.
        if lo == hi:
            continue
        sym = _symbol_for(cite, text)
        if sym is None:
            continue
        # A "symbol" that is just the cited file's own name is prose, not code.
        if sym == Path(cite_path).stem:
            continue
        if not _citation_still_valid(repo_file, sym, lo, hi):
            findings.append(
                Finding(
                    _rel(page.parent.parent.parent, page),
                    page.parent.name,
                    "dead_citation",
                    CONF_LIKELY,
                    f"{cite} no longer contains '{sym}' (cited {lo}-{hi}, {repo_name})",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# branch check (check 2)
# ---------------------------------------------------------------------------

_BRANCH_RE = re.compile(r"\b[Bb]ranch\s+([A-Za-z0-9][A-Za-z0-9_/.-]*)")
_BRANCH_STOPWORDS = frozenset(
    """is has now adds add can should rather merges merge discipline convention
    commits commit stacking the a an on in to for and or of with was were be been
    it its this that main master head dev trunk base tip""".split()
)
_BRANCH_PREFIXES = (
    "feat/",
    "fix/",
    "docs/",
    "doc/",
    "refactor/",
    "chore/",
    "ci/",
    "test/",
    "tests/",
    "agent/",
    "business/",
    "integrate/",
    "arch/",
    "origin/",
    "ws",
    "coord/",
    "requests/",
    "decisions/",
    "drift/",
    "draft/",
    "discovery/",
    "harness/",
    "miriah/",
    "soypete/",
)
_BRANCH_GONE_GUARDS = (
    "not pushed",
    "never merged",
    "no remote",
    "not on the remote",
    "not on remote",
    "lived on",
    "was on",
    "never existed",
    "no longer exists",
    "deleted",
    "removed",
    "not on the",
    "local only",
    "local-only",
)


def _branch_set(root: Path):
    names = set()
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/remotes",
                "refs/heads",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for r in out.stdout.split():
            for prefix in ("remotes/origin/", "origin/", "remotes/"):
                if r.startswith(prefix):
                    r = r[len(prefix) :]
            names.add(r)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        wt = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in wt.stdout.splitlines():
            if line.startswith("branch "):
                b = line.split()[-1]
                names.add(b.replace("refs/heads/", ""))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return names


def _looks_like_branch(tok: str) -> bool:
    if tok in _BRANCH_STOPWORDS:
        return False
    if "/" in tok:
        return True
    if tok.startswith(_BRANCH_PREFIXES):
        return True
    return "-" in tok and len(tok) > 3


# Repos the page may name that we do NOT track locally. If a page names one of
# these, a branch it references may live there, so we cannot verify it and skip.
_UNTRACKED_REPO = re.compile(
    r"\b(marketing[- ]?site|design[- ]?system|@haikeilabs/brand)\b",
    re.I,
)


def _check_dead_branch(page: Path, text: str, repos: dict):
    findings = []
    low = text.lower()
    if any(g in low for g in _BRANCH_GONE_GUARDS):
        return findings
    # Only verify a branch when the page names exactly one tracked repo. If it
    # names several, or a repo we do not track, the branch may live elsewhere.
    tok = _repo_name_tokens(text)
    if len(tok) != 1 or _UNTRACKED_REPO.search(text):
        return findings
    name = next(iter(tok))
    if name not in repos:
        return findings
    branch_set = _branch_set(repos[name])
    seen = set()
    for m in _BRANCH_RE.finditer(text):
        branch = m.group(1).rstrip(".,;:)")
        if not _looks_like_branch(branch) or branch in seen:
            continue
        seen.add(branch)
        if branch not in branch_set:
            findings.append(
                Finding(
                    _rel(page.parent.parent.parent, page),
                    page.parent.name,
                    "dead_branch",
                    CONF_POSSIBLY,
                    f"branch {branch} not on remote/local in {name}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# merged/closed PR check (check 3)
# ---------------------------------------------------------------------------

_PR_RE = re.compile(r"\bPRs?\b\s*_?\(?\s*#?_?\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?")
_EXPLICIT_REPO_PR = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d{1,4})")
_OPEN_ASSERT = re.compile(
    r"\b(open|opened|pending|unmerged|not merged|not-merged|must merge|cannot merge|"
    r"can't merge|dependent|depends on|blocked by|waiting on|stacked on|no pr|has no pr|"
    r"until|lands)\b",
    re.I,
)
_MERGE_ACK = re.compile(
    r"\b(merged|landed|closed|complete|completed|done|resolved|shipped|delivered|"
    r"now merged|is now)\b",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# A sentence that REPORTS another artifact's claim ("it presents ... as open
# PRs", "the checklist says ...") is not the page asserting the PR is open.
_REPORTING_VERB = re.compile(
    r"\b(presents|present|states|state|says|say|claims|claim|describes|describe|"
    r"lists|list|reports|report|shows|show|reads as|described as|worded as)\b",
    re.I,
)


def _pr_numbers(text: str):
    nums = []
    for m in _PR_RE.finditer(text):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        nums += list(range(a, b + 1))
    for m in _EXPLICIT_REPO_PR.finditer(text):
        nums.append(int(m.group(2)))
    return sorted(set(nums))


def _explicit_repos(text: str):
    return {m.group(1) for m in _EXPLICIT_REPO_PR.finditer(text)}


_REPO_DISPLAY = {
    "kei": r"\bkei\b(?!-)",
    "kei-agents": r"\bkei-agents\b",
    "pedro-tag": r"\bpedro-tag\b",
    "pedro-agentware": r"\bpedro-agentware\b|\bagentware\b(?!-)",
}


def _pr_repo_ties(text: str):
    """Map a PR number to the repo name(s) mentioned near it, e.g.
    'Kei-Agents PR #12' ties 12 -> kei-agents. A bare 'PR #12' has no tie."""
    ties = {}
    for m in _PR_RE.finditer(text):
        n = int(m.group(1))
        window = text[max(0, m.start() - 60) : m.end()].lower()
        for name, pat in _REPO_DISPLAY.items():
            if re.search(pat, window):
                ties.setdefault(n, set()).add(name)
    return ties


def _pr_repos_to_check(text: str, n: int, gh_by_token: dict):
    """GitHub repos to check for PR n, or None to skip. A PR number only means
    something in one repo: use the repo the page ties it to, else the single
    named repo, else skip (ambiguous)."""
    ties = _pr_repo_ties(text).get(n)
    if ties:
        repos = [gh_by_token[t] for t in ties if t in gh_by_token]
        return repos or None
    if len(gh_by_token) == 1:
        return list(gh_by_token.values())
    return None


def _check_merged_pr(page: Path, text: str, gh: GithubResolver):
    findings = []
    low = text.lower()
    if not _OPEN_ASSERT.search(low):
        return findings
    tok = _repo_name_tokens(text)
    gh_by_token = {t: TOKEN_TO_GH[t] for t in tok if t in TOKEN_TO_GH}
    for er in _explicit_repos(text):
        gh_by_token.setdefault(er, er)
    if not gh_by_token:
        return findings
    sentences = _SENTENCE_SPLIT.split(text)
    flagged = []  # (number, state) for one finding per page
    for n in _pr_numbers(text):
        repos_to_check = _pr_repos_to_check(text, n, gh_by_token)
        if not repos_to_check:
            continue
        state = None
        for repo in repos_to_check:
            s = gh.pr_state(repo, n)
            if s in ("MERGED", "CLOSED"):
                state = s
                break
            if s == "OPEN":
                state = "OPEN"
        if state not in ("MERGED", "CLOSED"):
            continue
        for sent in sentences:
            if not (f"#{n}" in sent or re.search(rf"\b{n}\b", sent)):
                continue
            if not _OPEN_ASSERT.search(sent):
                continue
            if _MERGE_ACK.search(sent):
                continue  # this sentence already acknowledges the merge
            if _REPORTING_VERB.search(sent):
                continue  # the page is reporting another artifact's claim
            flagged.append((n, state))
            break
    if flagged:
        worst = "MERGED" if any(s == "MERGED" for _, s in flagged) else "CLOSED"
        nums = ", ".join(f"#{n}" for n, _ in flagged)
        findings.append(
            Finding(
                _rel(page.parent.parent.parent, page),
                page.parent.name,
                "merged_pr",
                CONF_LIKELY if worst == "MERGED" else CONF_POSSIBLY,
                f"{nums} is/are {worst.lower()} but the page asserts them open/pending",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# subject normalization (checks 4, 5, 6)
# ---------------------------------------------------------------------------

_PREFIXES = (
    "coord_",
    "claims_",
    "requests_",
    "decisions_",
    "drift_",
    "draft_",
    "release_",
    "handoff_",
    "ack_",
    "blocker_",
    "entity_",
    "source_",
    "contract_change_",
    "plan_",
    "repos_",
    "contracts_",
    "delegated_",
)
_SUFFIXES = (
    "-claim",
    "-complete",
    "-completed",
    "-done",
    "-released",
    "-closed",
    "-pending",
    "-ack",
    "-release",
    "-handoff",
    "-superseded",
    "-implemented",
    "-merged",
    "-open",
    "-stale",
    "-correction",
    "-acknowledged",
    "-resolved",
    "-implemented",
    "-worker-claim",
    "-worker-completion",
)
_GENERIC = frozenset(
    """test tests docs doc code repo repos service schema database db key keys
    api group groups user users workspace workspaces org orgs tenant handler
    handlers route routes migration migrations check checks page pages file files
    line lines claim decision blocker request requests release handoff ack entity
    source contract change contradiction drift vs and the a an of to in on for
    with from by as is are was were be been it its this that these those no not
    new old open closed merged pending done complete completed fixed implemented
    resolved now only also so if then than at out up down over under per via using
    use used""".split()
)


def _subject_token(page: Path) -> str:
    stem = page.stem.lower()
    for p in _PREFIXES:
        if stem.startswith(p):
            stem = stem[len(p) :]
            break
    for s in _SUFFIXES:
        if stem.endswith(s):
            stem = stem[: -len(s)]
            break
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")


def _subject_tokens_set(page: Path):
    return {t for t in _subject_token(page).split("-") if t and t not in _GENERIC}


def _subjects_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 6 and (shorter in longer or longer in shorter):
        return True
    ta = {t for t in a.split("-") if t}
    tb = {t for t in b.split("-") if t}
    code = re.compile(r"^(r|d|ws|hai)-?\d+")
    for x in ta:
        if code.match(x) and x in tb:
            return True
    return False


# ---------------------------------------------------------------------------
# unresolved claim (check 4)
# ---------------------------------------------------------------------------


def _check_unresolved_claims(pages, stale_days: float, now: datetime):
    findings = []
    claims = [p for p in pages if p.parent.name == "claim"]
    closers = [p for p in pages if p.parent.name in ("release", "handoff", "ack")]
    for claim in claims:
        created = _page_created(claim)
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).total_seconds() / 86400.0
        if age_days < stale_days:
            continue
        subj = _subject_token(claim)
        resolved = False
        for closer in closers:
            cc = _page_created(closer)
            if cc is None:
                continue
            if cc.tzinfo is None:
                cc = cc.replace(tzinfo=timezone.utc)
            if cc < created:
                continue
            if _subjects_match(subj, _subject_token(closer)):
                resolved = True
                break
        if not resolved:
            findings.append(
                Finding(
                    _rel(claim.parent.parent.parent, claim),
                    "claim",
                    "unresolved_claim",
                    CONF_POSSIBLY,
                    f"claim older than {stale_days:g}d with no later release/handoff "
                    f"on subject '{subj}'",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# resolved blocker (check 5)
# ---------------------------------------------------------------------------

_BLOCKER_CODE = re.compile(r"\b([RD]-\d{2,4})\b")
_BLOCKS_PR = re.compile(r"\bBlocks?\s+PR\s*#?(\d{1,4})\b", re.I)


def _specific_shared_tokens(a: set, b: set):
    """Shared tokens that are real words (>=3 letters), not bare code fragments
    like 'r', '002', 'ws5'. The overlap must be a genuine subject word."""
    return {t for t in (a & b) if len(t) >= 3 and t[0].isalpha() and not t.isdigit()}


def _check_resolved_blockers(pages, gh: GithubResolver):
    findings = []
    blockers = [p for p in pages if p.parent.name == "blocker"]
    decisions = [p for p in pages if p.parent.name == "decision"]
    decision_texts = [(d, d.read_text()) for d in decisions]
    for b in blockers:
        text = b.read_text()
        b_created = _page_created(b)
        b_tokens = _subject_tokens_set(b)
        # (a) subject appears in a later decision
        for code in set(_BLOCKER_CODE.findall(text)):
            for d, dtext in decision_texts:
                d_created = _page_created(d)
                if d_created is None or b_created is None:
                    continue
                if d_created.tzinfo is None:
                    d_created = d_created.replace(tzinfo=timezone.utc)
                if b_created.tzinfo is None:
                    b_created = b_created.replace(tzinfo=timezone.utc)
                if d_created < b_created:
                    continue
                if re.search(r"\b" + re.escape(code) + r"\b", dtext):
                    d_tokens = _subject_tokens_set(d)
                    if _specific_shared_tokens(b_tokens, d_tokens):
                        findings.append(
                            Finding(
                                _rel(b.parent.parent.parent, b),
                                "blocker",
                                "resolved_blocker",
                                CONF_LIKELY,
                                f"subject {code} appears in later decision {d.name}",
                                related=_rel(b.parent.parent.parent, d),
                            )
                        )
                        break
            else:
                continue
            break
        else:
            # (b) "Blocks PR N" is now merged/closed
            for m in _BLOCKS_PR.finditer(text):
                num = int(m.group(1))
                before = text[max(0, m.start() - 12) : m.start()].lower()
                if "not" in before:
                    continue
                gh_by_token = {
                    t: TOKEN_TO_GH[t]
                    for t in _repo_name_tokens(text)
                    if t in TOKEN_TO_GH
                }
                repos_to_check = _pr_repos_to_check(text, num, gh_by_token)
                if not repos_to_check:
                    continue
                state = None
                for repo in repos_to_check:
                    s = gh.pr_state(repo, num)
                    if s in ("MERGED", "CLOSED"):
                        state = s
                        break
                if state in ("MERGED", "CLOSED"):
                    findings.append(
                        Finding(
                            _rel(b.parent.parent.parent, b),
                            "blocker",
                            "resolved_blocker",
                            CONF_POSSIBLY,
                            f"'Blocks PR {num}' but PR {num} is {state.lower()}",
                        )
                    )
                    break
    return findings


# ---------------------------------------------------------------------------
# contradicted by a newer page (check 6)
# ---------------------------------------------------------------------------

_RESOLUTION_WORDS = re.compile(
    r"\b(fixed|implemented|resolved|complete|completed|merged|no longer|chose|decided|"
    r"superseded|closed|landed|done)\b",
    re.I,
)


def _check_contradictions(pages):
    findings = []
    clusters = {}
    for p in pages:
        subj = _subject_token(p)
        if subj:
            clusters.setdefault(subj, []).append(p)
    for subj, group in clusters.items():
        cats = {p.parent.name for p in group}
        if "contradiction" not in cats:
            continue
        contrad = [p for p in group if p.parent.name == "contradiction"]
        for c in contrad:
            c_created = _page_created(c)
            for other in group:
                if other.parent.name == "contradiction":
                    continue
                o_created = _page_created(other)
                if o_created is None or c_created is None:
                    continue
                if o_created.tzinfo is None:
                    o_created = o_created.replace(tzinfo=timezone.utc)
                if c_created.tzinfo is None:
                    c_created = c_created.replace(tzinfo=timezone.utc)
                if o_created <= c_created:
                    continue
                if other.parent.name == "release" or _RESOLUTION_WORDS.search(
                    other.read_text()
                ):
                    findings.append(
                        Finding(
                            _rel(c.parent.parent.parent, c),
                            "contradiction",
                            "contradicted",
                            CONF_JUDGMENT,
                            f"contradiction on '{subj}' may be resolved by newer "
                            f"{other.parent.name} page",
                            related=_rel(c.parent.parent.parent, other),
                        )
                    )
                    break
    return findings


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_audit(
    wiki_path,
    repos=None,
    gh=None,
    stale_days: float = 7,
    now: Optional[datetime] = None,
    extra_repo_dirs=None,
):
    wiki_path = Path(wiki_path)
    if repos is None:
        repos = discover_repos(extra_repo_dirs)
    if gh is None:
        gh = GithubResolver()
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    pages = _coordination_pages(wiki_path)
    findings = []
    for page in pages:
        text = page.read_text()
        findings += _check_dead_citation(page, text, repos)
        findings += _check_dead_branch(page, text, repos)
        findings += _check_merged_pr(page, text, gh)
    findings += _check_unresolved_claims(pages, stale_days, now)
    findings += _check_resolved_blockers(pages, gh)
    findings += _check_contradictions(pages)

    checks = {}
    for f in findings:
        checks[f.check] = checks.get(f.check, 0) + 1

    order = {CONF_LIKELY: 0, CONF_POSSIBLY: 1, CONF_JUDGMENT: 2}
    findings.sort(key=lambda f: (order.get(f.confidence, 3), f.page, f.check))
    return AuditReport(findings=findings, pages_scanned=len(pages), checks=checks)

# ======================================================================
# Structural audit: orphans, broken links, unindexed, empty, stale inbox
# ======================================================================

import time as _time

from .capture import wiki_root as _wiki_root


@dataclass
class StructuralReport:
    """Report from a structural wiki audit."""
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


def structural_audit(
    wiki_path: Optional[Path] = None, stale_days: int = 7
) -> StructuralReport:
    """Scan the wiki for structural issues (orphans, broken links, etc).

    Read-only — never mutates the wiki, the inbox, or the index.
    """
    wiki = Path(wiki_path) if wiki_path else _wiki_root()
    wiki_dir = wiki / "wiki"
    index_file = wiki / "index.md"
    inbox_dir = wiki / "inbox"

    report = StructuralReport()

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
    page_refs: set[str] = set()
    for md in all_pages:
        rel = md.relative_to(wiki).as_posix()
        page_paths.add(str(md))
        page_paths.add(rel)
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
            target = raw_target.strip()
            resolved.append(target)
            inbound_links.setdefault(target, 0)
            inbound_links[target] += 1
        link_graph[rel] = resolved

    # --- orphans: pages with no inbound links from other wiki pages ---
    for md in all_pages:
        rel = md.relative_to(wiki).as_posix()
        cat = md.parent.name if md.parent != wiki_dir else "general"
        refs = [f"{cat}/{md.stem}", md.stem, rel]
        has_inbound = any(inbound_links.get(r, 0) > 0 for r in refs)
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
        body = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
        body = body.strip()
        if not body or len(body) < 20:
            report.empty_pages.append(md.relative_to(wiki).as_posix())
    report.total_empty = len(report.empty_pages)

    # --- stale inbox records ---
    if inbox_dir.exists():
        now = _time.time()
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
