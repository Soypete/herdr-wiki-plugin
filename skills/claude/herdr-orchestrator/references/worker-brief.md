# Worker brief

A worker starts with no knowledge of the plan, the other workers, or why this task exists. The brief is its whole scaffold. Most worker failures trace back to a brief that left something to guess.

Write each brief to `/tmp/briefs/<name>.md`, then send it with `herdr agent prompt <name> "$(cat /tmp/briefs/<name>.md)"`.

## Principles

- **One outcome.** A brief that asks for two unrelated things gets half of each.
- **Say why.** One or two sentences of purpose lets the worker make sensible calls you didn't anticipate.
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
- `<path/to/file>` — <why it matters>
- Plan: `wiki search "plan <goal>"` — see which tasks other workers own.

## Scope
- Change: <files/packages/areas>
- Do NOT touch: <paths owned by other workers or out of scope>
- Interfaces you must honor: <signatures, API contracts, schemas>

## Environment
- Repo/worktree: <path>   Branch: <branch>
- Stack: <"new stack via gh stack init" | "gh stack add <branch> on top of <parent>" | "not stacked: gh pr create --base <base>">

## Done means
1. Unit tests cover the change, including <specific cases>.
2. `<exact test command>` passes.
3. PR opened with `gh stack submit` (or `gh pr create`), with a description covering what/why/how-tested.
4. Reply with: PR URL, test command output summary, anything the reviewer should look at first.
Do not merge.

## Coordination
- Record durable decisions with `wiki capture --type decision ...`.
- If you change a shared interface: `wiki capture --type contract_change ... --link about:<page>`.
- If you are blocked: `wiki capture --type blocker ...`, then stop and say "BLOCKED: <one line>". Don't work around it.
- Before finishing, capture a `handoff` summarizing what you did and any loose ends.
```

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
- Stack: `gh stack init` — you are the bottom of the stack.

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
