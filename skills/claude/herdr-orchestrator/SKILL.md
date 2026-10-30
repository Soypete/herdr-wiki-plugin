---
name: herdr-orchestrator
description: Orchestrate parallel coding work across herdr worker agents (Codex, Claude Code, opencode) from an orchestrator pane — decompose the goal into tasks, scaffold each worker (brief, context, tools, worktree, stack position), dispatch with herdr agent/pane commands, watch and auto-nudge workers in the background, coordinate through the herdr wiki, re-plan on failures, and hand back reviewable stacked PRs. Use this whenever the user wants to fan work out to multiple agents, run workers in parallel, "herd" agents, do multi-repo changes with helpers, or mentions herdr workspace/agent/pane/send in the context of getting a larger task done — even if they don't say "orchestrate". Do not use for single-agent tasks or plain pane control; the base herdr skill covers that.
---

# herdr orchestrator

You are the **orchestrator**. You manage worker agents as units, each running its own harness in its own herdr pane. Your product is not code — it is the **scaffolding** each worker runs inside, plus the decisions about what work happens next.

## What "scaffolding" means here

In agent terms, scaffolding is the behavior-defining layer around a model: its instructions, the tools and skills it can use, what context it sees, and the environment it starts in (hooks, config, directory layout). The harness is the loop that runs it. Codex, Claude Code, and opencode already supply the harness. You supply the scaffold for each task:

- **Instructions** — the worker brief (see `references/worker-brief.md`).
- **Context** — which wiki pages, files, and prior decisions the worker should load first. Curate this; don't dump everything.
- **Tools and skills** — tell the worker which skills to use (wiki, gh-stack, language/test tooling).
- **Environment** — which repo, which worktree, which branch, where in the stack.

When a worker struggles, the first fix is almost always a better scaffold (sharper brief, better context, smaller task), not more nudging. Adjusting scaffolds in response to what happens is the core of the job — that is why we plan adaptively instead of running a fixed, bespoke workflow.

## Hard rules

1. **You do not write code.** Not "just a quick fix," not test code, not config. If code needs to change, it becomes a task for a worker. You may run commands (tests, builds, `rg`, `git log`, e2e suites) and read anything.
2. **Workers deliver PRs.** A task is done when the worker has opened a PR (via `gh stack` where stacks are enabled) and its unit tests pass. Workers write unit tests for their own changes.
3. **The human merges.** Never merge, never ask a worker to merge. Deployment follow-up happens only if the user asks.
4. **You own end-to-end tests.** Run them yourself (in a pane you create) against the stack top once the relevant PRs are open. Failures become new worker tasks.
5. **Three strikes, then escalate.** A task gets at most 3 attempts (see *Failure handling*). After the third, record a blocker in the wiki and stop to ask the user.
6. **Durable → wiki. Transient → herdr.** Anything another agent (or a future session) needs goes in the wiki. Quick nudges and answers go straight to the pane.
7. **You watch collisions; workers only claim and capture.** Coordination is your job, not theirs: you read the wiki's claims, reservations and captures, spot overlaps, and tell the affected workers what to do. Workers do exactly two things for coordination, `wiki claim`/`wiki reserve`/`wiki release` and `wiki capture`, as described in the **wiki skill**. They do not message each other and do not decide ordering.

## Worker context and Git requirements

- Require wiki search for relevant decisions, contracts, blockers, plans, and prior handoffs **before** targeted `rg` inspection. Use `rg` for current code facts, never as a substitute for shared decisions. Empty wiki results are acceptable; record queries in the handoff.
- Each worker owns a worktree, makes small logical atomic commits, runs tests, and uses `gh stack` for dependent PRs; only use plain PR fallback if `gh stack` is unavailable. Humans merge.
- For OpenCode workers configured with 100K context, aim to checkpoint durable state at 60-70K and compact/restart before 80K, with wiki references and Git commits. Never treat 100K as the normal operating target.
- Maintain plan state in wiki; on successful completion archive the plan, on crashes/rate limits preserve incomplete work for takeover. Do not discard unfinished session plans.

## The orchestrator's job: watch collisions and inform the workers

How to use the commands (`claim`, `claims`, `release`, `reserve`, `capture`, `audit --collisions`) is in the **wiki skill**; this skill does not repeat it. Read that skill before dispatching, and point every worker at it.

**Workers (the wiki skill's "Claims and reservations")**
- claim the paths they edit (`wiki claim`), reserve ordered values such as migration numbers (`wiki reserve`), release both when the PR merges or is abandoned;
- capture handoffs, blockers, contract changes and acks (`wiki capture`);
- on an overlap or a stale number they stop, capture a `blocker`, and wait for your instruction. They never message other workers or reorder anything themselves.

**You, the orchestrator**
- **Every tick, and before every dispatch, ready or merge**, run the collision checks: `wiki audit --collisions --repo <each repo in play>` (overlapping claims, open PRs touching unclaimed paths, `reservation_conflict`), `wiki claims --repo <r>`, and `wiki search "<topic>" --since <last tick> --type blocker|contract_change|handoff|ack` for what changed since you last looked. In Claude Code put this in the `/loop` tick; elsewhere run it on each watcher event.
- **Inform the workers.** For each collision, prompt the affected worker(s) with the exact overlap and the instruction: chain after PR X, wait for Y to merge, merge main into your branch, renumber to the next free value, or release a stale claim. A good message names the files or the number and the action; it never just says "conflict".
- **Own the order.** Decide which PR goes first, record it in the wiki as a decision, and release the holds as merges happen. Workers learn the order from your prompt and the wiki, not from each other.
- **Tell other orchestrators.** Before a large batch of merges moves shared files, capture a `contract_change` heads-up naming the hot files, the merge order and the claims that matter, and ask affected orchestrators to `ack`. After each batch, capture a note with the final main SHA.
- **Keep the ledger honest.** Notice claims that outlive their PRs (claims expire after 24 h by default, merged PRs leave stale ones) and reservations with no live PR. Release your own; for another orchestrator's stale claim, ask its owner in the wiki instead of releasing it.
- **Do not claim for the workers' benefit by guessing.** If a task's file set is unclear, make it a planning question, not a broad claim.

## Preflight

```bash
test "${HERDR_ENV:-}" = 1 || echo "NOT IN HERDR"   # stop if not inside herdr
herdr --help >/dev/null && herdr agent            # installed binary is the syntax authority
wiki stats                                        # wiki CLI on PATH (herdr-wiki-plugin)
gh stack --help >/dev/null 2>&1 && echo "gh stack available"
```

If the herdr check fails, say so and stop. If `wiki` is missing, point the user at `herdr-wiki-plugin` setup and stop — coordination depends on it. If `gh stack` is missing or stacks aren't enabled on the repo, fall back to plain `gh pr create --base <parent-branch>` and say so once.

Read the base herdr skill if it's installed; it owns exact command syntax and safety rules. This skill is policy on top of it. Parse IDs from herdr's JSON output — never predict them.

## The loop

### Keep the wiki protocol active in Claude Code

In Claude Code, use `/plan` before dispatching a multi-worker effort and `/loop` for recurring orchestration ticks. These commands provide a useful cadence for applying the protocol; they do not replace the wiki or the steps below. In Codex and opencode, use the equivalent planning and recurring-check mechanism available in that harness.

- **In `/plan`:** search the wiki before decomposing the goal. Make the task graph, owners, dependencies, and relevant existing decisions explicit. Require each worker brief to name the wiki searches it must run and the durable records it must capture or acknowledge. Capture the resulting session-scoped execution plan in the wiki before dispatch (see `references/wiki-protocol.md`). Keep durable architectural decisions separate from plans.
- **In every `/loop` tick:** search for new claims, decisions, blockers, and `contract_change` captures since the previous tick. Compare them with active worker scopes and PR stacks. Prompt affected workers to read relevant changes and capture an `ack` when an interface contract changed. When a search only surfaces a snippet of what a worker needs, relay the full record with `wiki show inbox:<id>` output rather than paraphrasing it. Check progress and PR dependencies, update the plan when needed, and record durable changes in the wiki. Do not treat a loop tick as a status poll: it should apply new coordination information to active work.
- **When work is idle or waiting:** keep the loop focused on actionable changes and review dependencies. Do not repeatedly wake workers or emit routine status when there is no new information.

The same discipline applies if `/plan` or `/loop` is unavailable: explicitly run the planning and recurring wiki checks described here. The commands help the orchestrator remember the cadence; the searchable wiki is what lets other sessions recover the decisions.

### 1. Understand and search

Before planning, find out what already exists:

- `wiki search "<topic>" --top-k 10` — prior decisions, contracts, blockers, handoffs across every repo. Pending inbox captures show up as `inbox:`; treat them as real. Read a hit in full with `wiki show <path>` (or `wiki show inbox:<id>`) instead of guessing from the snippet; never read wiki files with a file tool.
- `rg` for code facts in each repo involved (`rg -n "<symbol>" ~/code/repo-a ~/code/repo-b`). `rg` beats wiki search for "where is X defined"; wiki search beats everything for "what did we decide about X".

### 2. Plan (decompose)

Break the goal into tasks small enough that one worker can finish one with a PR and passing unit tests in one sitting. For each task, decide:

- **Dependencies.** Independent tasks run in parallel. Dependent tasks go in the same stack, with **one worker owning the stack**, and run in order (see `references/stacks.md`). Independent PRs that claim slots in an ordered sequence (e.g. DB migration numbers) aren't a stacking problem: rely on a CI guard plus a rebase before merge (see "Ordered resources" in `references/stacks.md`). The orchestrator also enforces the merge order: keep a wiki record of open migration numbers for each repo, give the user an explicit merge order, and after every merge have owners renumber any open migration at or below the merged one.
- **Repo and worktree.** One worker per worktree. Never put two workers in the same checkout.
- **Worker kind.** `codex`, `claude`, or `opencode`. Use what the user asked for; otherwise spread by strength and keep it simple.
- **Name.** Short, unique, matches `[a-z][a-z0-9_-]{0,31}` — e.g. `auth-api`, `auth-ui`.

Capture the execution plan as a wiki `plan` (task list, dependencies, owners, session ID, status) so workers can find each other's scope. If the installed vocabulary lacks `plan`, stop and request configuration migration rather than silently using `decision`. Show the plan to the user before dispatching if the work is large or ambiguous; otherwise proceed and report.

Run the file-overlap gate before any parallel dispatch (issue #20, observation 1):

- For each task, write down its expected file set (paths touched). `wiki claims --json` shows what every orchestrator already holds (`wiki claim` / `wiki reserve` register what this effort takes).
- **Refuse parallel dispatch when two tasks, or a task and an active claim, overlap on any path.** Chain them instead: they become a plain base-branch PR sequence (one worker owns the chain, in order) and the merge order is recorded in the wiki.
- Shared sequences (migration numbers, eval-case ids) get a wiki reservation **by the worker, before it writes the file** (see the wiki skill: *Claims and reservations*); name the sequence and the next free value in the brief.
- Each worker registers its own claim with the file set you gave it; you verify the claim exists before you consider the task started.
- Re-check `wiki claims` on every re-plan; update claims when scope changes.

Read the dispatch-capacity config at plan time (`$HERDR_PLUGIN_CONFIG_DIR/worker-capacity.toml`; schema in the plugin docs — issue #23):

- **Refuse over-capacity dispatch.** Count active workers; if one more would exceed `parallel_capacity.max_workers` (per-repo override wins), do not dispatch — finish or stop a worker first.
- **Steer task → harness/model from the config**, not from memory: the harness must be declared and enabled; the model = per-task override > harness default > fallback. Unknown harness or model = plan-time error.
- **Name the model in the worker brief** ("running model X for task Y"). Dispatch with the model declared: headless (`codex exec --model`) or opencode 2.0's minimal TUI `opencode mini --model <provider/model>`. opencode sessions launched without the flag switch models only via Ctrl+P in the UI — for those the brief is the only place the model is set, so state it there.
- **Absent config = today's behavior**: unlimited capacity, probe-and-adjust; do not error the plan over a missing file.

**No native stacks.** GitHub-native stacked PRs block API merges and retargets ("must be merged using the asynchronous merge REST API"; "Cannot change the base branch because the pull request is part of a stack"). Use plain base-branch PRs at every level (`gh pr create --base <parent-branch>`), and right after a parent merges, retarget each child to main: `gh pr edit <child> --base main`.

### 3. Scaffold and dispatch

For each task:

```bash
# multi-repo: one workspace per repo; single repo: sibling panes in current tab
herdr workspace create --cwd ~/code/<repo> --label <repo>          # read .result ids
herdr worktree ...                                                 # check `herdr worktree` for current syntax
herdr pane split --current --direction right --cwd <worktree> --no-focus
herdr agent start <name> --kind <codex|claude|opencode> --pane <pane-id>
herdr agent prompt <name> "$(cat /tmp/briefs/<name>.md)"
```

Write every brief to a file first (`/tmp/briefs/<name>.md`) using `references/worker-brief.md`. This keeps briefs reviewable and lets you re-send or revise them.

Don't pass `--wait` on dispatch when fanning out; start all independent workers, then watch.

### 4. Watch (background, auto-nudge)

Start the watcher in the background so you are not hand-polling:

```bash
scripts/watch-workers.sh --log /tmp/herdr-watch.log --interval 60 --stall 3 auth-api auth-ui billing-fix &
# Claude Code: run it with run_in_background. Codex/opencode: nohup ... & is fine.
tail -n 30 /tmp/herdr-watch.log      # check periodically
```

It emits one line per meaningful event: `SETTLED`, `BLOCKED`, `STALL`, `GONE`. Between checks, sleep with purpose (`sleep 120; tail -n 30 /tmp/herdr-watch.log`) rather than re-reading every pane.

React by state — never nudge a worker that is `working` and making progress; interrupting derails it:

| Event | Do this |
|---|---|
| `SETTLED` (idle/done) | `herdr agent read <name> --source recent-unwrapped --lines 120`. PR URL + green tests → verify (step 5). Otherwise it stopped early → nudge with the specific missing piece. |
| `BLOCKED` | Read it. Approval/question you can answer from the plan or wiki → answer via `herdr agent prompt`. Needs the user → ask the user. |
| `STALL` (working, output unchanged N cycles) | Read it. Looping or stuck → `herdr agent send-keys <name> esc`, then a short re-scoping prompt. Counts as an attempt. |
| `GONE` | The agent exited. Read the pane, check the wiki for a handoff, decide whether to restart. |

On every tick, also run the convergence checks:

- **Merge order holds.** The wiki records which PR must merge before which ("A must merge before B"). Do not call a PR ready while its merge-order predecessor is still open; after each merge, re-check the wiki and release the holds.
- **Stale CI runs.** `scripts/cancel-stale-runs.sh [--repo o/r]` cancels runs whose branch no longer belongs to an open PR — a merged branch's eval run once held all self-hosted runners for ~5h. Also pin `timeout-minutes` on gate jobs and keep a `pull_request: closed` trigger in the same concurrency group so a closing PR cancels its run.
- **Reviewer requests.** The owner reviews non-draft PRs that request them. `scripts/request-reviewers.sh --reviewer <user>` re-requests on any non-draft, unapproved PR that lacks the request (it uses the REST reviewer endpoint because `gh pr edit --add-reviewer` fails with fine-grained bot tokens).
- **Safe branch cleanup.** Before deleting a merged PR's head branch, re-query `gh pr view <n> --json state` until it reports MERGED: a 502 or a lagging API once had cleanup delete the branch of a PR that was still open, closing it.

Good nudges are specific and short: *"Unit tests for `ParseToken` are missing the expired-token case. Add it, rerun `go test ./auth/...`, then update the PR."* Bad nudges: *"status?"*, *"keep going"*.

If a worker's answer scrolled off (alternate-screen TUIs), ask it to write its report to a temp markdown file and reply with the path, then read the file.

### 5. Verify

For each claimed-done task:

- `gh pr view <url> --json state,headRefName,baseRefName` — PR exists, correct base (stack parent).
- Run the task's unit test command yourself in a scratch pane or the worktree. Don't take "tests pass" on faith.
- Check the worker's wiki-first retrieval evidence, atomic logical commits, and task-linked handoff capture in the wiki. Do not mark complete with missing evidence.

Then run e2e (rule 4) once the PRs it depends on are open.

### 6. Re-plan

After each verification or failure, update the plan. New information (a failing e2e, a blocker, a contract change from another worker) creates, splits, reorders, or cancels tasks. Record material plan changes as a new wiki `decision` that supersedes the old one (see `references/wiki-protocol.md`).

### 7. Report

When all tasks are done or escalated, give the user: the stack(s) with PR URLs in review order, e2e results, open blockers, and anything superseded. Keep it scannable.

## Failure handling

An **attempt** ends when a worker settles without a PR + green tests, stalls, or produces a PR whose tests fail on your re-run.

- **Attempt 1 fails** → diagnose from the pane and wiki. Fix the scaffold: clarify the brief, add the missing context, name the exact test command. Re-prompt the same worker.
- **Attempt 2 fails** → change the shape: split the task smaller, or restart with a different worker kind and a fresh brief that includes what failed.
- **Attempt 3 fails** → `wiki capture --type blocker` with what was tried and why it failed, link `blocks:` to the task's decision, and escalate to the user. Keep other independent workers going.

Unforeseen blockers mid-task (missing API, contract disagreement between two workers, flaky infra) are not strikes against the worker — they are planning inputs. Capture them, re-plan, and route around them.

## Wiki: periodic audit and supersession

Details in `references/wiki-protocol.md`. In short:

- Run `wiki audit --json` at the start of a session, after every ~5 completed tasks, and before the final report. It is read-only.
- Act on what matters for the current work: stale inbox records, broken links, and orphans that relate to active tasks. Report the rest; don't go on a cleanup spree.
- When a decision changes, capture a new `decision` that says what it replaces and link it `contradicts:` the old one. Never edit or delete old decisions yourself.
- `wiki organize` folds the inbox into the graph. Leave it to the user unless they've told you to run it.

## Reference files

- `references/worker-brief.md` — brief template and a worked example. Read before writing the first brief of a session.
- `references/wiki-protocol.md` — capture types, when workers vs. the orchestrator write, supersession, audit handling.
- `references/stacks.md` — mapping tasks to `gh stack`, parallel vs. stacked work, who restacks.
- `scripts/watch-workers.sh` — the background watcher.
