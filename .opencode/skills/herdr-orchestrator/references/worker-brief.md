# Worker brief

A worker starts with no knowledge of the plan, the other workers, or why this task exists. The brief is its whole scaffold. Most worker failures trace back to a brief that left something to guess.

Write each brief to `/tmp/briefs/<name>.md`, then send it with `herdr agent prompt <name> "$(cat /tmp/briefs/<name>.md)"`.

## Principles

- **One outcome.** A brief that asks for two unrelated things gets half of each.
- **Say why.** One or two sentences of purpose lets the worker make sensible calls you didn't anticipate.
- **Bounded context.** Search wiki before targeted `rg`; don't paste whole histories. For 100K OpenCode contexts, checkpoint at 60-70K and compact/restart near 80K.
- **Atomic history.** Require one logical change per commit; dependent PRs use `gh stack` and keep a single stack owner.
- **Point, don't paste.** Name the wiki searches and files to read; don't paste whole files into the prompt.
- **Make "done" checkable.** An exact test command and an exact deliverable.
- **Draw the fence.** Say what is out of scope and which files belong to other workers.
- **Tell it how to stop.** What to do when blocked, so it records the problem instead of improvising around it.

## Template

```markdown
# Task: <name> — <one-line outcome>

## Why
<1–2 sentences: what this enables and where it fits in the larger goal.>

## Context — read first
- `wiki search "<query>"` — <what they'll find: e.g. the token format decision>
- After those searches, use targeted `rg -n "<symbol>" <relevant/path>` to locate current implementation and tests; inspect only matching files.
- `<path/to/file>` — <why it matters>
- Plan: `wiki search "plan <goal>"` — see which tasks other workers own.

## Scope
- Change: <files/packages/areas>
- Do NOT touch: <paths owned by other workers or out of scope>
- Interfaces you must honor: <signatures, API contracts, schemas>

## Environment
- Repo/worktree: <path>   Branch: <branch>
- Stack (plain, base-branch PR): `gh pr create --base <parent-branch> <branch>`. Never GitHub-native stacks (they block API merges/retargets).

## Done means
1. Unit tests cover the change, including <specific cases>.
2. `<exact test command>` passes.
3. Changes are in small, logically atomic commits, each independently understandable.
4. PR opened with `gh stack submit` (or `gh pr create`), with a description covering what/why/how-tested.
5. A wiki `handoff` links task/plan, records wiki queries, changed commits, PR URL, tests and remaining work.
6. Reply with: PR URL, test command output summary, anything the reviewer should look at first.
Do not merge.

## Coordination
- Before editing, run every wiki search named above. If a relevant contract or decision conflicts with this brief, stop and report the conflict before changing the interface.
- Record durable decisions with `wiki capture --type decision ...`.
- If you change a shared interface: `wiki capture --type contract_change ... --link about:<page>`.
- If the orchestrator or another worker records a relevant contract change, read it and capture an `ack` before continuing against that interface.
- If you are blocked: `wiki capture --type blocker ...`, then stop and say "BLOCKED: <one line>". Don't work around it.
- Before finishing, capture a task-linked `handoff` summarizing wiki search queries (including empty results), decisions applied, atomic commits, PR URL, test results, and any loose ends.
```

Every brief ends with this **footer** — the coordination terms the worker agrees to (issue #20):

```markdown
## Footer
- **Files I own (claim):** <exact files/dirs from Scope>. Register them yourself before editing, per the wiki skill (*Claims and reservations*): `wiki claims --repo <r> --paths '<globs>'` first, then `wiki claim --repo <r> --paths '<globs>' --pr <n> --branch <b> --owner <your name> --expires 7d`, and `wiki release <id>` when the PR merges. For any ordered value (migration number, eval-case id) use `wiki reserve` BEFORE writing the file; the next free value is: <value>.
- **PR shape:** a plain base-branch PR (`gh pr create --base <parent-branch>`). No GitHub-native stacks: they block API merges and retargets.
- **Review:** the PR body requests review from the owner; opening a non-draft PR ready for review is the definition of done — not "PR open".
- **Scope discipline:** if I would touch a file outside my claim, stop and reply "OUT-OF-SCOPE: <file>" instead of editing it.
- **Coordination:** your only coordination tools are `wiki claim`/`reserve`/`release` and `wiki capture`. Do not message other workers and do not reorder anything. If your claim overlaps another or a number is already taken, capture a `blocker`, say "BLOCKED: <one line>", and wait for the orchestrator.
```

**One step per prompt for opencode workers.** opencode sessions drift when a brief gives context but not the exact single step — a one-line test fix once became 1.5h of rebase planning this way. Send one concrete step per prompt: file, line, expected value, and the test command (`<file>:<line>` — make X equal Y, then run Z). Interrupt (`esc`) with a smaller prompt if the worker has not pushed within N minutes.

## Worked example

```markdown
# Task: auth-api — add token refresh endpoint

## Why
Web clients currently log users out when the access token expires. This endpoint lets them refresh silently. auth-ui (another worker) builds the client side on top of your PR.

## Context — read first
- `wiki search "refresh token decision"` — we chose rotating refresh tokens, 14-day lifetime.
- `internal/auth/token.go` — existing issuance logic; reuse `signToken`.
- Plan: `wiki search "plan token refresh"`.

## Scope
- Change: `internal/auth/`, `api/routes.go`
- Do NOT touch: `web/` (auth-ui owns it)
- Interface: `POST /auth/refresh` → `{access_token, refresh_token, expires_in}`; auth-ui is coding against this shape.

## Environment
- Worktree: ~/code/app-wt/auth-api   Branch: token-refresh-api
- Stack (plain base-branch PR): `gh pr create --base main`.

## Done means
1. Unit tests for: valid refresh, expired refresh token, reused (rotated-out) refresh token.
2. `go test ./internal/auth/... ./api/...` passes.
3. PR via `gh stack submit`.
4. Reply with PR URL + test summary. Do not merge.

## Coordination
- If the response shape must change, capture a `contract_change` linked `about:` the refresh decision BEFORE changing it — auth-ui depends on it.
- Blocked → capture `blocker`, reply "BLOCKED: ...", stop.
- Finish with a `handoff` capture.
```

## Re-brief after a failed attempt

Don't resend the same brief. Add a short section at the top:

```markdown
## Previous attempt
- What happened: <e.g. tests failed on expired-token case; worker edited web/ which is out of scope>
- Change this time: <e.g. only touch internal/auth; expired case must return 401 not 500>
```
