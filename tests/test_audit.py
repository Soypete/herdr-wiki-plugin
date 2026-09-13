"""Audit: dead-code citations, dead branches, merged PRs, unresolved claims,
resolved blockers, and the read-only guarantee.

Repos are created as real (tiny) git repos under tmp_path so the checks run
hermetically. The wiki is a small tree of coordination pages.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from haikei_wiki.audit import run_audit

_NOW = datetime(2026, 1, 20, tzinfo=timezone.utc)


def _git_repo(tmp: Path, name: str, files=None, branches=()):
    import os

    root = tmp / name
    root.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=root, env=env, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, env=env, check=True)
    for b in branches:
        subprocess.run(["git", "branch", b], cwd=root, env=env, check=True)
        subprocess.run(
            ["git", "update-ref", f"refs/remotes/origin/{b}", "HEAD"],
            cwd=root,
            env=env,
            check=True,
        )
    return root


def _wiki(tmp: Path, pages):
    wiki = tmp / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "log.md").write_text("# Wiki Log\n")
    for rel, content in pages.items():
        p = wiki / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return wiki


def _page(title, category, created, body):
    return (
        f"---\ntitle: {title}\ncategory: {category}\ncreated: {created}\n---\n\n"
        f"{body}\n"
    )


class FakeGH:
    def __init__(self, states=None):
        self.states = states or {}

    def pr_state(self, repo, number):
        return self.states.get((repo, number))


def _checks(report):
    return {f.check for f in report.findings}


# --- check 1: dead code citation -------------------------------------------


def test_citation_that_still_resolves_is_not_flagged(tmp_path):
    kei = _git_repo(
        tmp_path,
        "kei",
        files={"cmd/foo.go": "package foo\n\nfunc myFunc() int {\n\treturn 1\n}\n"},
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/contradiction/x.md": _page(
                "x",
                "contradiction",
                "2026-01-01T00:00:00",
                "myFunc in cmd/foo.go:3-5 returns the count. (kei)",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert not report.findings, report.findings


def test_citation_of_deleted_file_is_flagged(tmp_path):
    kei = _git_repo(tmp_path, "kei", files={"cmd/other.go": "package x\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/contradiction/x.md": _page(
                "x",
                "contradiction",
                "2026-01-01T00:00:00",
                "the handler is at cmd/gone.go:10 in kei.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_citation" in _checks(report)
    f = [x for x in report.findings if x.check == "dead_citation"][0]
    assert "cmd/gone.go" in f.evidence and "kei" in f.evidence


def test_citation_range_whose_symbol_moved_is_flagged(tmp_path):
    # myFunc was at 3-5; it moved to line 50. The cited range no longer covers it.
    filler = "\n".join(f"// line {i}" for i in range(1, 48))
    kei = _git_repo(
        tmp_path,
        "kei",
        files={
            "cmd/foo.go": f"package foo\n\n{filler}\n\nfunc myFunc() int {{\n\treturn 1\n}}\n"
        },
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "myFunc in cmd/foo.go:3-5 returns the count. (kei)",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_citation" in _checks(report)
    f = [x for x in report.findings if x.check == "dead_citation"][0]
    assert "myFunc" in f.evidence


def test_citation_of_function_body_is_not_flagged(tmp_path):
    # The page cites the BODY of a function (def elsewhere). That is still valid.
    body = "\n".join(f"\t// step {i}" for i in range(1, 20))
    kei = _git_repo(
        tmp_path,
        "kei",
        files={
            "cmd/foo.go": "package foo\n\nfunc myFunc() int {\n"
            + body
            + "\n\treturn 1\n}\n"
        },
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/contradiction/x.md": _page(
                "x",
                "contradiction",
                "2026-01-01T00:00:00",
                "myFunc in cmd/foo.go:5-12 does the work. (kei)",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert not report.findings, report.findings


def test_citation_with_unresolvable_repo_is_skipped(tmp_path):
    # Bare filename present in two repos, page names both -> ambiguous -> skip.
    kei = _git_repo(tmp_path, "kei", files={"roles.go": "package r\n"})
    tag = _git_repo(tmp_path, "pedro-tag", files={"roles.go": "package r\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "see roles.go:94-97 in kei and pedro-tag.",
            )
        },
    )
    report = run_audit(
        wiki, repos={"kei": kei, "pedro-tag": tag}, gh=FakeGH(), now=_NOW
    )
    assert "dead_citation" not in _checks(report)


def test_single_line_citation_is_not_symbol_checked(tmp_path):
    # A single line is too imprecise to judge by symbol; only the file must
    # exist. The symbol moved, but a single-line cite is not flagged.
    filler = "\n".join(f"// line {i}" for i in range(1, 48))
    kei = _git_repo(
        tmp_path,
        "kei",
        files={
            "cmd/foo.go": f"package foo\n\n{filler}\n\nfunc myFunc() int {{\n\treturn 1\n}}\n"
        },
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "myFunc in cmd/foo.go:3 returns the count. (kei)",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_citation" not in _checks(report)


def test_symbol_equal_to_filename_stem_is_not_flagged(tmp_path):
    # A "symbol" that is just the cited file's own name is prose, not code.
    kei = _git_repo(
        tmp_path,
        "kei",
        files={
            "cmd/runtime_installations.go": "package x\n\nfunc a() {}\nfunc b() {}\n"
        },
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "runtime_installations in cmd/runtime_installations.go:1-2. (kei)",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_citation" not in _checks(report)


def test_relative_path_suffix_match_resolves(tmp_path):
    # Pages cite paths relative to a subdir (e2e/flows.spec.ts for
    # frontend/e2e/flows.spec.ts). A unique suffix match resolves it.
    kei = _git_repo(
        tmp_path,
        "kei",
        files={"frontend/e2e/flows.spec.ts": "export const t = 1\n"},
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "the e2e suite is e2e/flows.spec.ts in kei.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_citation" not in _checks(report)


# --- check 2: dead branch ---------------------------------------------------


def test_deleted_branch_is_flagged(tmp_path):
    kei = _git_repo(
        tmp_path, "kei", files={"main.go": "package main\n"}, branches=("feat/alive",)
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "Task on branch feat/gone in kei.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_branch" in _checks(report)
    f = [x for x in report.findings if x.check == "dead_branch"][0]
    assert "feat/gone" in f.evidence


def test_live_branch_is_not_flagged(tmp_path):
    kei = _git_repo(
        tmp_path, "kei", files={"main.go": "package main\n"}, branches=("feat/alive",)
    )
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "Task on branch feat/alive in kei.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_branch" not in _checks(report)


def test_branch_acknowledged_as_not_pushed_is_not_flagged(tmp_path):
    kei = _git_repo(tmp_path, "kei", files={"main.go": "package main\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/release/x.md": _page(
                "x",
                "release",
                "2026-01-01T00:00:00",
                "Done on branch feat/gone in kei. NOT pushed, NO PR opened.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_branch" not in _checks(report)


def test_dead_branch_multi_repo_is_skipped(tmp_path):
    # The page names two tracked repos; the branch may live in either, so we
    # cannot verify it and skip.
    kei = _git_repo(tmp_path, "kei", files={"main.go": "package main\n"})
    tag = _git_repo(tmp_path, "pedro-tag", files={"main.go": "package main\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "Task on branch feat/gone in kei and pedro-tag.",
            )
        },
    )
    report = run_audit(
        wiki, repos={"kei": kei, "pedro-tag": tag}, gh=FakeGH(), now=_NOW
    )
    assert "dead_branch" not in _checks(report)


def test_dead_branch_untracked_repo_is_skipped(tmp_path):
    # The page names a repo we do not track (marketing-site); the branch may
    # live there, so we skip.
    kei = _git_repo(tmp_path, "kei", files={"main.go": "package main\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "Task on branch feat/gone in kei, mirrored in marketing-site.",
            )
        },
    )
    report = run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    assert "dead_branch" not in _checks(report)


# --- check 3: merged PR -----------------------------------------------------


def test_open_pr_now_merged_is_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "All kei connector PRs #313-#317 are OPEN.",
            )
        },
    )
    gh = FakeGH({("HaikeiLabs/kei", n): "MERGED" for n in range(313, 318)})
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "merged_pr" in _checks(report)
    f = [x for x in report.findings if x.check == "merged_pr"][0]
    assert f.confidence == "LIKELY STALE"
    assert "#313" in f.evidence


def test_page_that_acknowledges_merge_is_not_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "PR #317 is merged; the provider interface is in main.",
            )
        },
    )
    gh = FakeGH({("HaikeiLabs/kei", 317): "MERGED"})
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "merged_pr" not in _checks(report)


def test_merged_pr_degrades_gracefully_when_gh_unavailable(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "All kei connector PRs #313-#317 are OPEN.",
            )
        },
    )
    # gh unavailable -> pr_state always None -> no PR findings, no crash.
    report = run_audit(wiki, repos={}, gh=FakeGH({}), now=_NOW)
    assert "merged_pr" not in _checks(report)


def test_merged_pr_reporting_verb_is_not_flagged(tmp_path):
    # The page REPORTS another artifact's claim ("it presents ... as open PRs"),
    # it does not itself assert the PR is open.
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "The checklist presents kei connector PR #313 as an open PR.",
            )
        },
    )
    gh = FakeGH({("HaikeiLabs/kei", 313): "MERGED"})
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "merged_pr" not in _checks(report)


def test_merged_pr_ambiguous_repo_is_skipped(tmp_path):
    # The page names two repos and does not tie the PR to either, so we cannot
    # tell which repo the PR belongs to and skip.
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "PR #12 is open. (kei and kei-agents)",
            )
        },
    )
    gh = FakeGH(
        {("HaikeiLabs/kei", 12): "MERGED", ("HaikeiLabs/Kei-Agents", 12): "MERGED"}
    )
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "merged_pr" not in _checks(report)


def test_merged_pr_tied_to_specific_repo(tmp_path):
    # "Kei-Agents PR #12" ties the PR to Kei-Agents even though kei is also
    # named; the merged Kei-Agents PR is flagged (not the closed kei #12).
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x",
                "claim",
                "2026-01-01T00:00:00",
                "Kei-Agents PR #12 remains open. (kei and kei-agents)",
            )
        },
    )
    gh = FakeGH(
        {("HaikeiLabs/kei", 12): "CLOSED", ("HaikeiLabs/Kei-Agents", 12): "MERGED"}
    )
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "merged_pr" in _checks(report)
    f = [x for x in report.findings if x.check == "merged_pr"][0]
    assert f.confidence == "LIKELY STALE"


# --- check 4: unresolved claim ---------------------------------------------


def test_claim_with_matching_later_release_not_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/coord_bar-claim.md": _page(
                "bar", "claim", "2026-01-01T00:00:00", "bar work"
            ),
            "wiki/release/coord_bar-done.md": _page(
                "bar done", "release", "2026-01-05T00:00:00", "bar released"
            ),
        },
    )
    report = run_audit(wiki, repos={}, gh=FakeGH(), stale_days=7, now=_NOW)
    assert "unresolved_claim" not in _checks(report)


def test_claim_without_later_release_is_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/coord_foo-claim.md": _page(
                "foo", "claim", "2026-01-01T00:00:00", "foo work"
            ),
        },
    )
    report = run_audit(wiki, repos={}, gh=FakeGH(), stale_days=7, now=_NOW)
    assert "unresolved_claim" in _checks(report)


def test_recent_claim_is_not_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/coord_foo-claim.md": _page(
                "foo",
                "claim",
                "2026-01-19T00:00:00",
                "foo work",  # 1 day old
            ),
        },
    )
    report = run_audit(wiki, repos={}, gh=FakeGH(), stale_days=7, now=_NOW)
    assert "unresolved_claim" not in _checks(report)


# --- check 5: resolved blocker ---------------------------------------------


def test_blocker_whose_blocks_pr_merged_is_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/blocker/r-008-identity.md": _page(
                "R-008 identity",
                "blocker",
                "2026-01-01T00:00:00",
                "R-008 identity ownership. Blocks PR 387, does not block PR 386. (kei)",
            )
        },
    )
    gh = FakeGH({("HaikeiLabs/kei", 387): "MERGED", ("HaikeiLabs/kei", 386): "MERGED"})
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "resolved_blocker" in _checks(report)
    f = [x for x in report.findings if x.check == "resolved_blocker"][0]
    assert "387" in f.evidence


def test_blocker_with_no_resolution_is_not_flagged(tmp_path):
    wiki = _wiki(
        tmp_path,
        {
            "wiki/blocker/r-008-identity.md": _page(
                "R-008 identity",
                "blocker",
                "2026-01-01T00:00:00",
                "R-008 identity ownership. (kei)",
            )
        },
    )
    gh = FakeGH({})
    report = run_audit(wiki, repos={}, gh=gh, now=_NOW)
    assert "resolved_blocker" not in _checks(report)


def test_resolved_blocker_needs_a_real_shared_word(tmp_path):
    # A bare workstream code (WS1) shared between a blocker and a later
    # decision is not enough; there must be a real subject word in common.
    wiki = _wiki(
        tmp_path,
        {
            "wiki/blocker/b.md": _page(
                "b",
                "blocker",
                "2026-01-01T00:00:00",
                "R-010 credential scoping is blocked. (kei)",
            ),
            "wiki/decision/d.md": _page(
                "d",
                "decision",
                "2026-01-05T00:00:00",
                "R-010 resolved for a different topic entirely.",
            ),
        },
    )
    report = run_audit(wiki, repos={}, gh=FakeGH(), now=_NOW)
    assert "resolved_blocker" not in _checks(report)


# --- read-only guarantee ----------------------------------------------------


def test_audit_is_read_only(tmp_path):
    kei = _git_repo(tmp_path, "kei", files={"cmd/foo.go": "package foo\n"})
    wiki = _wiki(
        tmp_path,
        {
            "wiki/claim/x.md": _page(
                "x", "claim", "2026-01-01T00:00:00", "myFunc in cmd/foo.go:1-3. (kei)"
            )
        },
    )
    before = {str(p.relative_to(wiki)): p.read_bytes() for p in wiki.rglob("*.md")}
    run_audit(wiki, repos={"kei": kei}, gh=FakeGH(), now=_NOW)
    after = {str(p.relative_to(wiki)): p.read_bytes() for p in wiki.rglob("*.md")}
    assert before == after
    assert not (wiki / "inbox" / "processed").exists()
    assert not (wiki / "inbox" / "rejected").exists()
