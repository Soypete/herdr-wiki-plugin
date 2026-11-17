# Wiki hygiene: auditing and cleaning the coordination graph

A swarm writes a lot of coordination pages: claims, blockers, decisions and
handoffs. Most of them are true when written and go stale later, when a PR
merges, a branch is deleted or a later decision settles a blocker. Stale pages
mislead the next worker that runs `wiki search`. This page covers how to find
them (`wiki audit`), what to do with each one (withdraw, supersede or, rarely,
delete), and a worked example of a large cleanup.

The best cleanup is the one you never need. Workers keep their own records
current with the **PR closeout protocol**. This page does not repeat it; read
the "PR closeout" section of
[`skills/claude/wiki/SKILL.md`](../skills/claude/wiki/SKILL.md), the
"PR closeout" bullet in [`agent-instructions.md`](../agent-instructions.md),
and the closeout section of the worker brief in
[`skills/claude/herdr-orchestrator/references/worker-brief.md`](../skills/claude/herdr-orchestrator/references/worker-brief.md).

## Running the audit

```
wiki audit                    # human-readable, strongest signal first
wiki audit --json             # for scripting a cleanup
wiki audit --stale-days 14    # age threshold for unresolved_claim (default 7)
```

The audit is read-only. It reports candidates and never changes a page. Only
`organize` writes pages, and only `wiki supersede` and `wiki withdraw` write
lifecycle status. The audit looks only at coordination categories (claim,
decision, blocker, contradiction, handoff, ack, contract_change, release,
entity, source), not at imported or notes pages.

Each finding carries a confidence: `LIKELY STALE`, `POSSIBLY STALE` or
`NEEDS JUDGMENT`. `gh` is optional. Without it (or unauthenticated), the PR
checks produce no findings instead of failing, so an empty `merged_pr` list on
a machine without `gh` means "not checked", not "clean".

## What each check means

| Check | What it found | What it usually means | Usual action |
| --- | --- | --- | --- |
| `merged_pr` | The page says a PR is open, pending, blocked, stacked or waiting, but `gh` reports that PR MERGED or CLOSED. | The worker never closed out. | Claims, blockers and progress handoffs: supersede them with the final MERGED/CLOSED handoff. If there is none yet, write it first. |
| `dead_branch` | A branch named on the page is gone from the repo (remote, local and worktrees). Pages that say "not pushed", "no remote" and similar are skipped. | Usually the branch was deleted after a merge. Sometimes the branch was never pushed. | Weak on its own. On a handoff, leave it (see below). On a claim or blocker, check the PR, then supersede or withdraw. |
| `dead_citation` | A cited `path:line` no longer resolves, the line range has moved out of the named symbol, or the page names a repo that is not checked out locally. | The code moved on. The page described the code at one point in time. | Leave handoffs alone. For a claim or decision whose argument depends on the citation, re-check the code and supersede it with a current page. |
| `unresolved_claim` | A claim older than `--stale-days` with no later release, handoff or ack on the same subject. | The worker may have finished without closing out, or the subject matching missed the closer. | Weak signal. Spot-check a few; do not bulk-act on it. |
| `resolved_blocker` | A blocker whose subject shows up in a later decision, or whose "Blocks PR N" PR is now merged or closed. | The blocker was resolved and nobody said so. | Supersede it `--by` the decision or the final handoff that resolved it. |

The audit can also report `contradicted` pages (two pages on one subject with
different conclusions). Those are always `NEEDS JUDGMENT`: read both pages and
decide.

## Handoffs are point-in-time records

A handoff says what was true when it was written: "PR #12 open at head abc123,
CI green, waiting on review." That record stays true *as history* after the PR
merges. It is only wrong if someone reads it as the current state.

So you do not delete a handoff, and you usually do not withdraw it. You add a
**final handoff** that states the end state (`<repo>#<N> MERGED <sha8>` or
`<repo>#<N> CLOSED (<reason>)`) and **supersede** the earlier handoffs by it.
Superseded pages still show in search, ranked lower and labelled as
historical, so the trail survives and the current answer shows first.

For the same reason, a handoff flagged only for `dead_citation` or
`dead_branch` is usually fine as it is. The branch was deleted after the merge
and the code moved on; that is what happens after a handoff.

## Withdraw, supersede or delete

| Command | Use it when | Effect |
| --- | --- | --- |
| `wiki supersede <page> --by <page-or-url> [--reason ...]` | The page **was true** and has been overtaken: the PR merged, the blocker got resolved, a later decision replaced this one. | Status `superseded`, with `superseded_by` pointing at the replacement. Still readable and searchable. |
| `wiki withdraw <page> --reason "..."` | The page **was wrong or is now meaningless**, and no single page replaces it: a stale claim on abandoned work, a blocker that was never real, a decision that was never carried out. | Status `withdrawn`, with the reason. Still readable and searchable. |
| `wiki delete page <path>` | The page is **junk**: a test capture, an accidental duplicate with no history value. Owner only. | The file is removed and the deletion is logged in `log.md`. |

Rules of thumb:

- If something replaces the page, supersede it. If nothing does, withdraw it.
- Workers never delete. Deleting is the owner's call, and only for pages with
  no history value.
- One cleanup **decision** page can be the `--by` target for many superseded
  pages. That keeps the reason in one place.
- Never edit wiki page files by hand. Use the lifecycle commands so the
  single-writer rule holds.

## Worked example: the 2026-11-15 cleanup

This is the owner-approved cleanup of 2026-11-15, recorded in the wiki
decision "Wiki cleanup 2026-11-15: stale blockers, claims, decisions
withdrawn; completed handoffs superseded".

**Starting point.** `wiki audit` reported **953 findings on 702 of 3460
pages**. Many were records workers left behind after their PR merged:
claims, blockers and "PR open" handoffs (no exact breakdown was recorded).

**What was done:**

1. **Withdrew 47 stale blockers and claims.** Their PR had merged, their
   branch was gone, or a later decision had resolved them. No single page
   replaced each one, so withdraw (with a reason) fit better than supersede.
2. **Withdrew 59 audit-flagged decisions** (dead branch, dead citation or
   merged PR).
3. **Superseded 52 completed handoffs** by **one cleanup decision page**: the
   handoffs for work whose PR had merged. They stay as history and point at
   the cleanup decision.
4. **Deleted 1 junk page** (a test capture under `ack/`). Nothing else was
   deleted.

**Left alone on purpose:**

- Handoffs flagged **only** for dead citations or dead branches. They are
  point-in-time records, and the flag just means the code and branches moved
  on after them.
- `contract_change` and `ack` pages. They record what was agreed at a given
  time and stay valid as history.
- **480 unresolved claims** older than 7 days. The signal was too weak to act
  on in bulk.

**What came next.** The cleanup was followed by the PR closeout protocol, so
each worker closes out its own records when its PR merges. Orchestrators run
`wiki audit` every few tasks and act on `merged_pr`, `dead_branch` and
`resolved_blocker` findings in their own herd before the list grows.

## A cleanup checklist

1. `wiki audit --json > audit.json` and keep the file. It is the baseline for
   your numbers.
2. Group the findings by check and category. Start with `merged_pr` and
   `resolved_blocker`, which have the strongest signal.
3. Spot-check a sample of each group with `wiki show <page>` and
   `gh pr view <N> -R <owner>/<repo> --json state,mergedAt`.
4. Write one cleanup **decision** page that states the scope, the counts and
   what you leave alone, and get the owner's approval.
5. Apply `wiki supersede ... --by <cleanup decision>` and
   `wiki withdraw ... --reason "..."` page by page. Do not delete anything
   unless the owner names it.
6. Re-run `wiki audit` and record the before and after counts in the
   decision or a handoff.
