# Merge on approve: reviewing a swarm's PRs from your phone

The owner of a swarm is often away from the keyboard: traveling, in meetings,
reviewing from the GitHub mobile app. This workflow lets the owner do the
one thing only they can do, **approve the exact code**, and leaves the
mechanical rest to agents: noticing the approval, merging, watching the
deploy and recording the result in the wiki.

## The flow

1. **Workers and orchestrators open PRs.** Each PR is a draft until the
   worker has re-read its diff and CI is green, then it is marked ready.
   Workers never merge.
2. **The owner approves on the exact head.** An Approve review on GitHub is
   tied to the commit it was given on. A later push means the approval no
   longer covers the head, and the PR needs approving again.
3. **A watcher announces mergeable PRs.**
   [`scripts/approval-watch.sh`](../scripts/approval-watch.sh) prints one
   `READY-TO-MERGE` line per PR that is:
   - approved by the owner **on the current head sha**,
   - green on CI (every check passes),
   - `CLEAN` (mergeable, no conflicts, branch protections satisfied),
   - not a draft, and
   - based on the **repo's default branch**.
4. **A session merges and follows through.** For each announced PR, a
   session (an orchestrator, or one it assigns):
   - squash-merges with the head pinned, so nothing pushed after the
     approval can slip in:
     ```
     gh pr merge <N> -R <owner>/<repo> --squash --match-head-commit <head-sha>
     ```
   - watches the CI or deploy the merge triggers until it finishes. If it
     fails, the session stops and captures a `blocker` with the run URL and
     a log excerpt. It does not retry or roll back without the owner.
   - captures a final handoff and closes out the PR's wiki records with the
     PR closeout protocol (see the "PR closeout" section of
     [`skills/claude/wiki/SKILL.md`](../skills/claude/wiki/SKILL.md)).
5. **The owner hears back on GitHub.** Questions to the owner go into one
   short PR comment. Agents posting as the owner's account end every comment
   with an invisible marker, `<!-- orch-session -->`.
   [`scripts/owner-comment-watch.sh`](../scripts/owner-comment-watch.sh) then
   picks out the comments the owner typed themselves (no marker) so a session
   can answer them.

The owner's approval is the gate. The watcher and the merging session only
check that the approval still covers the code being merged.

## Lessons

**Never merge a stacked PR into its parent branch after the parent was
squash-merged.** A squash merge puts the parent's changes on the default
branch as one new commit. The parent branch itself is left behind and does
not reach the default branch any more. If a child PR is then merged into
that parent branch, its changes land on a branch nothing uses. This
happened on a `playground` repo stack: #141 was merged into its parent's
branch after the parent had been squash-merged, and its change had to be
re-landed as #143 against the default branch. The watcher only announces PRs
whose base is the default branch. For a stack: merge the bottom PR,
retarget the next PR to the default branch, wait for CI, and get a fresh
approval on its head.

**Check `state` before `mergeStateStatus`.** GitHub reports
`mergeStateStatus: UNKNOWN` for a PR that is already merged. A script that
reads only the merge state sees UNKNOWN, retries, and can report a merged
PR as stuck. Read `state` first and stop if it is not `OPEN`. UNKNOWN on an
open PR usually means GitHub is still computing mergeability, so check again
on the next cycle.

**Held PRs and other people's PRs are skipped.** An approval does not always
mean "merge now". The owner may approve a PR and hold it for a release
window, a dependent change or someone else's sign-off. List those in
`SKIP_PRS`. PRs authored by other people, and dependency-bot PRs, are
merged by their authors or their own process, not by the swarm. Exclude
them with `EXCLUDE_AUTHORS`, or allow only the swarm's identities with
`ONLY_AUTHORS`.

Related: the swarm's worker identity, which lets the owner formally approve
the swarm's PRs, is set up in
[`setting-up-a-worker-identity.md`](setting-up-a-worker-identity.md).

## Running the watchers

Both scripts are read-only: they print lines and never merge, comment or
change anything except their own state files. Both need `gh`, authenticated.
`owner-comment-watch.sh` also needs `python3`, and it sees private-repo
events only when `gh` is authenticated as the owner. Each script runs a fixed
number of polls (`CYCLES`) and then prints a "re-arm" line, so run it in the
background and start it again when it exits. Set `CYCLES=0` to poll forever.

```
# Announce PRs approved by the owner in two orgs, holding two PRs
OWNER_LOGIN=octo-owner \
WATCH_ORGS="octo-owner octo-org" \
SKIP_PRS="octo-org/api#440 octo-org/api#441" \
EXCLUDE_AUTHORS="*dependabot* *renovate* teammate-login" \
  scripts/approval-watch.sh
# READY-TO-MERGE octo-org/api#452 author=swarm-bot head=1a2b3c4d

# Surface comments the owner typed (no agent marker)
OWNER_LOGIN=octo-owner WATCH_ORGS="octo-org" scripts/owner-comment-watch.sh
# OWNER-COMMENT octo-org/api#452: please split the migration out
```

`approval-watch.sh`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OWNER_LOGIN` | the `gh`-authenticated user | Login whose approval counts |
| `WATCH_ORGS` | `$OWNER_LOGIN` | Space-separated users/orgs to search |
| `SKIP_PRS` | none | Space-separated `owner/repo#N` held PRs |
| `EXCLUDE_AUTHORS` | `*dependabot*` | Space-separated author globs to skip |
| `ONLY_AUTHORS` | unset (any author) | If set, only these authors are announced |
| `STATE_FILE` | `${TMPDIR:-/tmp}/approval-watch.seen` | Seen-list; each `repo#N@head` is announced once |
| `INTERVAL` | `180` | Seconds between polls |
| `CYCLES` | `9` | Polls before exiting; `0` = forever |
| `SEARCH_LIMIT` | `60` | Max PRs per search |

`owner-comment-watch.sh`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OWNER_LOGIN` | the `gh`-authenticated user | Login whose comments to watch |
| `WATCH_ORGS` | unset (every repo) | Only print events in these users'/orgs' repos |
| `MARKER` | `orch-session` | Comments containing this are agent comments and are skipped |
| `STATE_DIR` | `${TMPDIR:-/tmp}/owner-comment-watch` | Seen-list and start time; events before the first run are ignored |
| `INTERVAL` | `150` | Seconds between polls |
| `CYCLES` | `12` | Polls before exiting; `0` = forever |

A PR with no CI checks is never announced, because `gh pr checks` does not
report it as passing. Merge those by hand.
