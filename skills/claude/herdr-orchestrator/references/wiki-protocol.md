# Wiki protocol

The wiki (herdr-wiki-plugin, `wiki` CLI) is the shared, durable memory between the orchestrator, workers, and future sessions. It is local, so there are no permission concerns, and one wiki spans every repo — which is what makes multi-repo coordination work.

## Mechanics that matter

- `wiki capture` writes one atomic record to the inbox. It is visible to `wiki search` immediately (marked `inbox:`), so other agents see it right away without `organize`.
- `wiki organize` is the single writer to the graph. Leave it to the user unless told otherwise.
- The vocabulary is closed. A capture with an unknown `--type` or link predicate is rejected; don't invent new ones. Adding types means editing `tbox.toml`, which is the user's call.
- `wiki audit` is read-only. `wiki delete` is exact-match and logged — the orchestrator does not delete.

Types: `claim, contradiction, decision, entity, source, blocker, handoff, ack, release, contract_change`
Predicates: `derived_from, contradicts, supports, about, relates_to, answers, acknowledges, blocks`

## Durable vs transient

Goes in the wiki (durable): anything another worker, the user, or a future session needs to know — plans, decisions, interface contracts, blockers, handoffs, audit findings you act on.

Goes through `herdr agent prompt` (transient): nudges, clarifying answers that only matter to this worker right now, "rerun the tests", "scope back to X".

Test: if you'd need to repeat it to a second worker or remember it tomorrow, it's durable.

## Who captures what

| Situation | Who | Type | Links |
|---|---|---|---|
| Session plan / task graph | orchestrator | `decision` | `about:` goal |
| Design choice within a task | worker | `decision` | `about:` plan or component |
| Shared interface changes | worker (before changing) | `contract_change` | `about:` the contract's decision |
| Cannot proceed | worker or orchestrator | `blocker` | `blocks:` the task/plan decision |
| Task finished | worker | `handoff` | `about:` plan |
| Worker confirms it read a contract change | worker | `ack` | `acknowledges:` the contract_change |
| Two sources disagree | anyone | `contradiction` | `contradicts:` both |
| Stack/PR set ready for review | orchestrator | `release` | `about:` plan |

Title captures so they search well: lead with the component and the gist — `auth refresh: rotating tokens, 14d lifetime`.

## Contract changes across workers

When a worker captures a `contract_change`, the orchestrator finds every worker whose scope touches that contract and prompts each one: *"Contract change: <title>. Read it with `wiki search "<title>"`, adjust, and capture an `ack`."* Check for the acks on the next watch cycle.

## Supersession

There is no `supersedes` predicate in the starter vocabulary. Until the user adds one:

1. Capture a new `decision` whose title starts with `SUPERSEDES: <old title> —` and whose content says what changed and why.
2. Link it `contradicts:<old-page-or-inbox-id>` and `derived_from:` whatever prompted the change (a blocker, a failed e2e, a contract_change).
3. Tell affected workers directly (transient) and ask for an `ack` if the change alters their task.

Never edit or delete the old decision; the history is the point. If the user adds a `supersedes` predicate to `tbox.toml`, use it instead of `contradicts`.

## Periodic audit

Run `wiki audit --json` at session start, after about every 5 completed tasks, and before the final report.

- **Stale inbox records** related to current work → mention to the user that `wiki organize` is due.
- **Broken links / orphans** related to current work → capture a fix (new record with the right links) if the correct target is clear; otherwise list it in the report.
- **Decisions that current work has overtaken** (you'll spot these while searching, not from audit output) → supersede as above.
- Everything unrelated to the current session → one line in the final report. Don't clean up the whole wiki unasked.

## Search order

1. `wiki search` for anything about intent, decisions, contracts, or who's doing what.
2. `rg` for code facts inside repos — faster and exact.
3. Only then open files or ask a worker.
