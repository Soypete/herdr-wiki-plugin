# A Shared Wiki for Agent Swarms

**A practical coordination architecture for parallel coding agents across Herdr sessions and harnesses**

**Author:** SoyPete Tech

**Status:** Working draft

**Date:** 2026-10-04

## Executive summary

Parallel coding agents can produce a lot of useful work, but adding agents also adds handoffs. Each worker sees a slice of the task, and each orchestrator sees a slice of the larger effort. When decisions, file ownership, and interface changes live only in a conversation, the next session can miss them, repeat work, or build against an outdated assumption.

This paper describes a practical coordination setup built around Herdr, a shared LLM-Wiki, and agent-specific skills. Herdr provides persistent sessions, panes, workspaces, and worktrees for Claude Code, Codex, and OpenCode. The wiki acts as durable shared memory across those harnesses and across independent orchestrators. Skills give each orchestrator and worker a repeatable protocol for reading that memory, scoping work, stacking dependent pull requests, handling changes, and reporting results.

The central idea is simple: treat coordination information as an engineering artifact. Record durable decisions and interface changes in a searchable place; keep worker briefs narrow and concrete; make dependencies visible in PR structure; and use the orchestrator to relay changes to the people and agents affected by them.

In practice, this has helped me surface overlap earlier and avoid some repeated work. I have also seen fewer merge conflicts, but I have not measured a baseline or calculated a conflict-reduction rate. The examples here show how the process works; they do not establish a statistical result.

## The problem: parallel work loses context at every handoff

An agent swarm is not simply a group of agents running at once. It is a set of workers making local decisions while sharing code, interfaces, deployment resources, and product constraints. Their work may span repositories and harnesses, while each model session has only its own working context.

This creates predictable failure modes:

- A worker repeats discovery because a previous session's findings were never recorded.
- Two workers edit the same route table or package wiring without knowing about each other.
- A client is built against an endpoint shape that another worker has since changed.
- A pull request is merged before its dependency, or a migration number collides with another branch.
- An orchestrator compresses a long history into a short handoff and drops the reason behind a decision.

More prompt text helps only within the session that receives it. It does not give a different harness or a later session a reliable way to find the same information. Coordination needs durable state, ownership boundaries, and an explicit way to propagate changes.

## Architecture

The setup has four cooperating parts:

```text
                  ┌────────────────────────────────┐
                  │ Shared LLM-Wiki                │
                  │ decisions · claims · contracts │
                  │ blockers · handoffs · acks      │
                  └───────────────▲────────────────┘
                                  │ search / capture
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
┌───────┴────────┐       ┌────────┴───────┐        ┌────────┴───────┐
│ Herdr session  │       │ Herdr session  │        │ Herdr session  │
│ Claude Code    │       │ Codex          │        │ OpenCode       │
│ orchestrator   │       │ orchestrator   │        │ orchestrator   │
└───────┬────────┘       └────────┬───────┘        └────────┬───────┘
        │ briefs / dispatch        │                         │
        └─────────────┬────────────┴─────────────┬───────────┘
                      ▼                          ▼
               workers in isolated worktrees and PR stacks
```

### Herdr: sessions and workspaces

Herdr manages the terminal workspaces where orchestrators and workers run. An orchestrator decomposes a goal, creates isolated worktrees, starts workers in panes, gives each worker a brief, and watches for meaningful state changes. Different sessions can work on separate initiatives while still consulting the same wiki.

The harness is the agent's execution loop: Claude Code, Codex, or OpenCode. Herdr supplies the surrounding work environment and task scaffolding. The orchestrator's job is to choose what should happen next, provide the right context, and turn worker output into reviewable work.

### The wiki: durable shared memory

The wiki is a searchable Markdown knowledge base with provenance-aware capture. Agents search it for prior decisions, contracts, claims, and blockers; they capture information another worker or future session will need. The plugin in this repository provides shared search and capture behavior across Claude Code, Codex, and OpenCode.

Search is intentionally simple and inspectable. `wiki search` scans the wiki pages and `index.md` with a case-insensitive text search, and it also searches pending inbox JSON by title and content unless `--no-inbox` is passed. Results from pages and inbox records are combined and ranked with lightweight scores: title matches rank above content matches, and superseded or withdrawn pages are down-ranked so historical decisions remain discoverable without crowding out current ones. This is lexical retrieval, not vector or semantic search; query wording matters.

The inbox separates fast capture from graph organization. `wiki capture` atomically writes a JSON record under `inbox/` and appends an operation entry to `log.md`. Other sessions can find that pending record immediately through search, marked `inbox:`. Search is read-only: it does not organize, move, or edit the capture. A single `wiki organize` pass is the writer that turns accepted captures into pages under `wiki/<type>/`, updates `index.md`, appends to `log.md`, and moves each record into `inbox/processed/` or `inbox/rejected/`. This lets agents exchange new decisions quickly while keeping one controlled path for editing the organized graph.

Deletion is also explicit and auditable. `wiki delete` requires an exact page path or inbox record ID. Deleting a page updates the index where needed; deleting an inbox record moves it to `inbox/deleted/`. Both operations append a dated entry to `log.md`, identifying the deleted page or inbox record. The operation log therefore lets the study verify completed deletions and distinguish them from a request or failed attempt.

The wiki's capture vocabulary is deliberately constrained. The current types include `decision`, `claim`, `contract_change`, `blocker`, `handoff`, `ack`, and `release`. Link predicates express relationships such as `blocks`, `acknowledges`, and `derived_from`. This structure gives an orchestrator more useful search targets than a pile of untyped notes.

The wiki is not the live worker control channel. A short instruction such as “rerun this test” belongs in Herdr's agent prompt. A design choice, interface change, or handoff that another session needs belongs in the wiki. The rule is: transient instructions go to the pane; durable knowledge goes to the wiki.

### Skills: repeatable operating procedures

Skills encode the process so each session does not have to reconstruct it from scratch. The Herdr orchestrator skill explains how to search the wiki, decompose work, scaffold a worker brief, dispatch workers, monitor progress, verify PRs, and re-plan after new information arrives.

Its supporting references provide more specific procedures:

- **Wiki protocol:** which events deserve durable captures, how workers acknowledge contract changes, and how to preserve superseded decisions.
- **Worker brief:** a template that names one outcome, the context to read, files in scope, interfaces to honor, the exact done condition, and how to report a blocker.
- **Stacks:** when to run tasks independently versus sequentially, how one owner manages a stack, and how to restack after a lower layer changes.
- **Watcher script:** reports meaningful worker events such as settled, blocked, stalled, or gone, so the orchestrator can react to state rather than poll every pane.

These skills are available in harness-specific forms. Their intent is consistent across harnesses: preserve the protocol while allowing each tool to use its native commands.

### Git and pull requests: visible dependency structure

Independent tasks can run in separate worktrees and PRs. Dependent tasks in one repository belong in a stack, with one owner responsible for its order and restacks. A stack makes the dependency visible in the PR bases and lets the next layer build against a settled interface before the earlier work merges.

Stacks do not solve every ordering problem. Database migration numbers, for example, are shared ordered resources rather than code dependencies. Those need their own tracking and checks. The process distinguishes these cases instead of assuming that every related change belongs in one stack.

## Operating loop

In my Claude sessions, I use `/plan` to make the wiki protocol explicit before dispatch and `/loop` to bring it back during recurring orchestration ticks. The slash commands are a practical reminder mechanism: `/plan` calls for wiki-backed scope and ownership, while `/loop` checks for new claims and contract changes and routes them to affected workers. Other harnesses need the same cadence through their own planning and recurring-task tools.

The recurring workflow is:

1. **Search before planning.** Search the wiki for decisions, claims, contracts, blockers, and current plans. Use source code search to establish where behavior lives.
2. **Decompose by outcome and dependency.** Independent tasks can run in parallel. Dependent changes in the same repository get one stack owner and a clear layer order.
3. **Scaffold each worker.** Give it one outcome, exact files or packages, relevant context, required skills, test commands, and a checkable definition of done. Assign a fresh worktree.
4. **Record durable coordination.** Capture the plan and decisions. Before changing a shared interface, capture a contract change and notify affected workers; ask them to acknowledge it. Put the required wiki searches and acknowledgements into each worker brief.
5. **Watch for meaningful events.** On each `/loop` tick, search for new claims, decisions, blockers, and contract changes, then compare them with active scopes and PR stacks. Read a settled or blocked worker's output and respond to the specific issue. Do not interrupt workers that are making progress or wake them when there is no actionable change.
6. **Verify and review.** Check the PR base and stack, run the relevant checks, examine comments, and make sure the handoff is recorded. Merge only after the required approval and CI checks.
7. **Re-plan.** A conflict, missing dependency, or changed contract is new planning information. Record it, adjust the stack, and keep unrelated work moving.

The process is adaptive. If a worker repeatedly stalls, improve its scaffold or split the task. Repeating “keep going” without changing the task definition usually adds noise rather than progress.

## Example: coordinating the API gateway and policy-sync herds

In one active effort, a policy-sync orchestrator was moving catalog and console handlers out of root packages. A separate API-gateway orchestrator was preparing route changes in the same repositories. Both herds had multiple workers, and the overlap could have produced conflicting edits to route wiring or broken routes consumed by other services.

The policy-sync orchestrator recorded claims for its active stacks and searched for other orchestrators' claims. When the gateway herd announced its changes, the orchestrators compared scopes and dependencies. They agreed that the gateway work would begin with catalog route groups outside the cleanup stack. Audit query, credentials, connector invoke, external groups, and CLI device-auth work would wait until the relevant root-cleanup layers merged, then move into the new internal packages.

They also made cross-repository contracts explicit. The console changes would preserve audit-encryption routes. The gateway would keep two catalog routes working for the runtime during its move to a gateway host. The gateway herd would leave the CLI proxy version pin to the policy-sync work. Workers were told to search for `GW contract_change` before editing routes and to rebase after the upstream changes landed.

The result was a change in work order and clear ownership before workers collided in the same files. The decision was visible to both orchestrators and could be retrieved by workers in either harness. That is the useful unit of coordination: not just “we talked,” but “the dependency and contract are now searchable, and the work is sequenced accordingly.”

## Example: changing the encryption design without losing the history

A second example came from audit-log encryption. The initial design assumed a server-held key. A closer review exposed a mismatch with the actual goal: sensitive tool arguments should not be readable by the service. The design shifted to customer-held public keys and opt-in encryption, with digest-only records when no key is registered.

That decision affected catalog APIs, runtime behavior, the CLI, console UI, documentation, and the user-facing key-rotation flow. Rather than letting each worker infer the new design from chat, the orchestrator updated the shared contract and redirected the affected workers. The ADR recorded the rationale; separate workers could implement the catalog registry, runtime encryption, CLI, and UI against that contract. A later decision required users to acknowledge that key rotation affects future records while older records still need their original private keys.

The useful property here is not that the first design was right. It was not. The useful property is that the change was made durable, affected workers were identified, and the implementation was re-scoped before the old assumption spread further.

## What this does and does not establish

The examples show coordination mechanisms operating across sessions: shared claims, contract changes, explicit dependencies, staged work, and worker acknowledgements. In my experience, merge conflicts have decreased since using this process. I have not collected a consistent baseline, conflict count, or denominator, so I cannot claim a measured reduction rate.

The first prospective observation window is **October 4, 2026, 10:28 a.m. to 5:00 p.m. Mountain Time**. Every 30 minutes, record the state of each Herdr session and the wiki activity visible in its history. Treat each named Herdr session as its own isolated orchestrator context; count its worker panes under that session, and record cross-session messages as transfers between contexts. The opening manual snapshot found four running Herdr sessions and 2,020 wiki pages. At 10:45, the first collected session excerpt reported that 35 of 36 requested stale pages had been deleted, with no failures; the `log.md` tail contained 35 page-deletion entries and the wiki inventory reported 1,985 pages. This is an initial descriptive result: the log confirms the 35 completed deletions, while the 36th requested page was not reported as deleted. `log.md` entries record the date but not the time, so session history is needed to assign operations to 30-minute intervals. Verify successful captures, organization, and deletions against the corresponding inbox state and `log.md` entries; do not infer effects from a prompt alone.

For each session, count wiki command calls separately from resulting records:

- **Calls:** `wiki search`, `wiki stats`, `wiki capture` by capture type, `wiki organize`, `wiki audit`, and `wiki delete` by target kind. For search, record whether the query returned an organized page, a pending `inbox:` record, both, or neither.
- **Records and changes:** claims, decisions, contract changes, acknowledgements, blockers, handoffs, releases, superseding decisions, organized pages, audited findings, and completed deletions.
- **Coordination outcomes:** a decision or contract relayed to another session; a worker acknowledgement; a change to task scope, route contract, ownership, or PR order; repeated discovery; rework; and merge conflicts or conflict-free rebases.

Keep separate counts for attempted calls and confirmed effects. For example, a request to delete 36 stale pages is not 36 completed deletions until the deletion command succeeds and the result is verified. Likewise, count a wiki warning as an early coordination event, but call it an avoided conflict only when the record shows the warning changed the work before conflicting edits landed. Attribute every event to its originating session and link cross-session handoffs, so activity in one isolated context is not mistaken for activity in another.

This short window can support a complete descriptive finding about whether and how the coordination workflow was used: the operation counts show adoption, while traced examples show whether records moved decisions or changed work. It cannot establish that the workflow caused fewer conflicts. A larger retrospective analysis of the roughly 32 sessions mentioned in the project notes could use the same definitions alongside PR and rebase histories, with workload and concurrency reported as context.

## Practical adoption

Start with a single shared wiki and three habits: search before work, capture durable decisions, and make each worker's scope explicit. In Claude Code, use `/plan` to put those requirements into the task graph and worker briefs, then `/loop` to keep checking the wiki and nudging workers when relevant coordination changes arrive. Add stacks when there are real dependencies. Keep tasks narrow enough that a worker can finish with a reviewable PR. Use skills to teach the procedure consistently across harnesses, and retain the session histories needed to understand where the procedure helps or fails.

Do not measure success by worker count or raw PR volume. Measure whether useful work reaches review with less repeated discovery, fewer late surprises, and clear ownership. Parallelism is valuable when the coordination cost stays visible and manageable.

## Conclusion

Agent swarms need a shared memory and a protocol for using it. Herdr gives sessions and workers a place to run; the wiki lets separate orchestrators find the same decisions; skills make the coordination routine repeatable; and stacked PRs express code dependencies in a form reviewers can inspect.

This is pragmatic infrastructure for limiting information dilution. It does not eliminate mistakes or prove a reduction in conflicts on its own. It gives agents a way to preserve the context that matters, tell each other when a contract changes, and adjust the order of work before one session's assumptions become another session's rework.

## References

- [Herdr Wiki Plugin repository](https://github.com/Soypete/herdr-wiki-plugin) — plugin, wiki CLI, and harness-specific skills.
- [Herdr](https://herdr.dev) — terminal workspace manager for AI coding agents.
- [Purdue OWL: White Paper—Organization and Other Tips](https://owl.purdue.edu/owl/subject_specific_writing/professional_technical_writing/white_papers/organization_and_other_tips.html) — guidance to begin with a summary, explain the problem before the solution, use specific headings and examples, and include works cited.
- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — background for the personal LLM-Wiki pattern referenced by the plugin.
