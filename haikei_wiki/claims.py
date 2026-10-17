"""Structured claims: "who holds files X in repo Y right now?".

Issue #10: two orchestrators in the same repos collide on files, migration
numbers and whole features because claims are free-text prose that keyword
luck must surface. This module gives coordination a queryable form:

- `wiki claim --repo owner/name --paths '<glob>' [--branch b] [--pr n]
  [--owner o] [--expires 24h]` — a **path-level claim** ("PR X owns dir A, B
  until merged")
- `wiki release <claim-id>` — release when the PR merges or the work is done
- `wiki claims [--repo r] [--paths glob] [--json]` — list active claims and
  flag overlaps between them
- `wiki reserve --kind migration --repo r --value 074` — reserved sequences
  (migration numbers, eval-case ids, …) checked against each other
- `wiki audit --collisions` — diffs open PRs (`gh`) against active claims:
  overlapping claims, open PRs that touch claimed paths without a claim;

Storage: one JSON file per claim/reservation under `<wiki>/claims/`, written
atomically (O_EXCL capture-style). Claims expire (`--expires`, default 24 h):
lapsed ones are inactive for `wiki claims` but stay in the directory as
history. A shared backend (git remote sync) is deliberately left for a
follow-up; this landed the queryable local form first.
"""

import fnmatch
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CLAIMS_DIR = "claims"


class ClaimError(ValueError):
    pass


@dataclass
class Claim:
    id: str
    kind: str  # "path" | "reservation"
    repo: str
    owner: str = ""
    created_at: str = ""
    expires_at: str = ""
    status: str = "active"  # active | released
    # path claims
    paths: list[str] = field(default_factory=list)
    branch: str = ""
    pr: int = 0
    # reservations
    sequence_kind: str = ""
    value: str = ""

    def to_record(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "repo": self.repo,
            "status": self.status,
            "owner": self.owner,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "paths": self.paths,
            "branch": self.branch,
            "pr": self.pr,
            "sequence_kind": self.sequence_kind,
            "value": self.value,
        }


def claims_dir(wiki_path: Path | None = None) -> Path:
    from .capture import wiki_root

    return Path(wiki_path) if wiki_path else wiki_root() / _CLAIMS_DIR


def _atomic_write(path: Path, record: dict) -> None:
    payload = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(payload)
    os.replace(tmp, path)


def _all() -> list[tuple[Path, dict]]:
    d = claims_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append((p, json.loads(p.read_text())))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def create_claim(
    repo: str,
    paths: list[str],
    branch: str = "",
    pr: int = 0,
    owner: str = "",
    expires: str = "24h",
    wiki_path: Path | None = None,
) -> Claim:
    """Register that this PR/branch owns `paths` in `repo` until merged."""
    repo = repo.strip()
    if "/" not in repo:
        raise ClaimError(f"--repo must be owner/name, got {repo!r}")
    if not paths or not all(p.strip() for p in paths):
        raise ClaimError("claim requires --paths '<glob[,glob]>'")
    exp = _parse_expires(expires)
    now = datetime.now(timezone.utc)
    c = Claim(
        id=_new_id(),
        kind="path",
        repo=repo,
        owner=owner,
        created_at=_ts(now),
        expires_at=_ts(exp),
        paths=[p.strip() for p in paths],
        branch=branch,
        pr=pr,
    )
    d = claims_dir(wiki_path)
    d.mkdir(parents=True, exist_ok=True)
    _atomic_write(d / f"{c.id}.json", c.to_record())
    return c


def create_reservation(
    repo: str,
    sequence_kind: str,
    value: str,
    owner: str = "",
    wiki_path: Path | None = None,
) -> Claim:
    """Reserve a shared sequence value (e.g. migration 074) for `repo`."""
    repo = (repo or "").strip()
    value = (value or "").strip()
    if "/" not in repo:
        raise ClaimError(f"--repo must be owner/name, got {repo!r}")
    if not value:
        raise ClaimError("reserve requires --value (e.g. 074)")
    if not sequence_kind:
        raise ClaimError("reserve requires --kind (migration|eval-case|...)")
    c = Claim(
        id=_new_id(),
        kind="reservation",
        repo=repo,
        owner=owner,
        created_at=_ts(datetime.now(timezone.utc)),
        sequence_kind=sequence_kind.strip().lower(),
        value=value,
    )
    d = claims_dir(wiki_path)
    d.mkdir(parents=True, exist_ok=True)
    _atomic_write(d / f"{c.id}.json", c.to_record())
    return c


def release(claim_id: str, wiki_path: Path | None = None) -> str:
    """Mark a claim released (paths free again). Returns the released id."""
    d = claims_dir(wiki_path)
    matches = [
        p
        for p, rec in _all()
        if rec.get("id") == claim_id or rec.get("id", "").startswith(claim_id)
    ]
    if not matches:
        raise ClaimError(f"no such claim: {claim_id}")
    if len(matches) > 1:
        raise ClaimError(
            f"ambiguous claim id {claim_id}: {len(matches)} prefixes match"
        )
    p = matches[0]
    rec = json.loads(p.read_text())
    rec["status"] = "released"
    rec["released_at"] = _ts(datetime.now(timezone.utc))
    _atomic_write(p, rec)
    return claim_id


def _parse_expires(spec: str) -> datetime:
    spec = (spec or "24h").strip().lower()
    try:
        if spec.endswith("h"):
            return datetime.now(timezone.utc) + timedelta(
                hours=float(spec[:-1] or "24")
            )
        if spec.endswith("d"):
            return datetime.now(timezone.utc) + timedelta(days=float(spec[:-1]))
        if spec.endswith("m"):
            return datetime.now(timezone.utc) + timedelta(minutes=float(spec[:-1]))
        return datetime.fromisoformat(spec)
    except (ValueError, TypeError) as e:
        raise ClaimError(f"bad --expires {spec!r} (use 24h, 7d, or an ISO date)") from e


def _active(
    records: list[tuple[Path, dict]], now: datetime | None = None
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for _, rec in records:
        if rec.get("status") != "active":
            continue
        if rec.get("expires_at"):
            try:
                if datetime.fromisoformat(rec["expires_at"]) < now:
                    continue
            except ValueError:
                pass
        out.append(rec)
    return out


def list_claims(
    repo: str | None = None,
    paths: str | None = None,
    include_expired: bool = False,
    wiki_path: Path | None = None,
) -> tuple[list[dict], list[dict]]:
    """Active claims (+ reservations), and the overlap pairs among them.

    Overlap = same repo, path claims whose globs match each other, or
    duplicate reservations with the same (repo, kind, value).
    """
    records = _all()
    active = _active(records)
    if repo:
        active = [r for r in active if r.get("repo") == repo]
    if paths:
        wanted = [g.strip() for g in paths.split(",") if g.strip()]
        active = [
            r
            for r in active
            if r.get("kind") == "path"
            and any(
                _match(target, want) for target in r.get("paths", []) for want in wanted
            )
        ]
    overlaps = _overlap_pairs(
        [r for r in active if repo is None or r.get("repo") == repo]
    )
    return active, overlaps


def _match(path: str, glob: str) -> bool:
    glob = glob.rstrip("/")
    if any(ch in glob for ch in "*?["):
        return fnmatch.fnmatch(path, glob) or path.startswith(glob.rstrip("*"))
    return path == glob or path.startswith(glob + "/") or glob.startswith(path + "/")


def _overlap_pairs(active: list[dict]) -> list[dict]:
    """Pairs of active claims holding the same paths, or duplicate
    reservations of the same sequence value."""
    overlaps = []
    claims = [r for r in active if r.get("kind") == "path"]
    for i, a in enumerate(claims):
        for b in claims[i + 1 :]:
            if a["repo"] != b["repo"]:
                continue
            shared = [
                pa
                for pa in a.get("paths", [])
                for pb in b.get("paths", [])
                if _match(pa, pb) or _match(pb, pa)
            ]
            if shared:
                overlaps.append(
                    {
                        "kind": "path_overlap",
                        "claims": [a["id"], b["id"]],
                        "repo": a["repo"],
                        "paths": sorted(set(shared)),
                    }
                )
    seen = {}
    for r in active:
        if r.get("kind") != "reservation":
            continue
        key = (r["repo"], r.get("sequence_kind"), str(r.get("value")))
        if key in seen:
            overlaps.append(
                {
                    "kind": "reservation_conflict",
                    "claims": [seen[key], r["id"]],
                    "repo": r["repo"],
                    "sequence": f"{r.get('sequence_kind')} {r.get('value')}",
                }
            )
        else:
            seen[key] = r["id"]
    return overlaps


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------
# open PRs vs claims (`wiki audit --collisions`)
# --------------------------------------------------------------------------


def gh_open_prs(repo: str, gh_bin: str = "gh", timeout: float = 20.0):
    """Open PRs for a repo with touched files: [(number, branch, files)]."""
    import subprocess

    try:
        out = subprocess.run(
            [
                gh_bin,
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--json",
                "number,title,files,headRefName",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return None
    prs = []
    for item in data:
        files = [f.get("path", "") for f in item.get("files", [])]
        prs.append((int(item.get("number", 0)), item.get("headRefName", ""), files))
    return prs


def collisions(
    repos: list[str] | None = None,
    wiki_path: Path | None = None,
    gh_bin: str = "gh",
) -> tuple[dict, list[str]]:
    """Claim/PR collisions per repo. Returns (report, notes).

    Report keys: per repo {"overlapping_claims": [...],
    "unclaimed_prs": [{number, files}], "claims_vs_pr": [...]}. `gh` failing
    degrades to a note (offline-safe), not an error.
    """
    active = _active(_all())
    if repos:
        active = [r for r in active if r.get("repo") in repos or repos is None]
    by_repo: dict[str, list[dict]] = {}
    for rec in active:
        by_repo.setdefault(rec["repo"], []).append(rec)
    if repos:
        for repo in repos:
            by_repo.setdefault(repo, [])
    notes: list[str] = []
    report: dict = {}
    for repo, claims in sorted(by_repo.items()):
        row: dict = {
            "claims": len(claims),
            "overlapping_claims": [],
            "unclaimed_prs": [],
            "claims_vs_pr": [],
        }
        overlaps = _overlap_pairs([r for r in claims if r.get("kind") == "path"])
        row["overlapping_claims"] = [
            {"claims": o["claims"], "paths": o["paths"]} for o in overlaps
        ]
        prs = gh_open_prs(repo, gh_bin=gh_bin)
        if prs is None:
            notes.append(f"gh unavailable for {repo}: skipped PR diff")
        else:
            path_claims = [r for r in claims if r.get("kind") == "path"]
            for number, branch, files in prs:
                matched_claim = next(
                    (
                        c
                        for c in path_claims
                        if c.get("pr", 0) == number
                        or (c.get("branch") and c.get("branch") == branch)
                    ),
                    None,
                )
                if matched_claim is None:
                    row["unclaimed_prs"].append(
                        {"number": number, "branch": branch, "files": len(files)}
                    )
                    continue
                other_files = [
                    f
                    for f in files
                    if not any(_match(f, pat) for pat in matched_claim.get("paths", []))
                ]
                if other_files:
                    row["claims_vs_pr"].append(
                        {
                            "number": number,
                            "claim": matched_claim["id"],
                            "unclaimed_files": other_files[:20],
                        }
                    )
        report[repo] = row
    return report, notes


def reservations_taken(repo: str | None = None, wiki_path: Path | None = None) -> dict:
    """Already-reserved sequence values, keyed by (repo, kind) -> [values]."""
    out: dict = {}
    for _, rec in _all():
        if rec.get("kind") != "reservation":
            continue
        if rec.get("status") != "active":
            continue
        if repo and rec.get("repo") != repo:
            continue
        key = f"{rec['repo']}#{rec.get('sequence_kind')}"
        out.setdefault(key, []).append(str(rec.get("value")))
    return out
