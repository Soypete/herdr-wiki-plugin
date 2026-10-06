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

There is a small benchmark for the herdr-orchestrator skill. On October 1, 2026, OpenCode running DeepSeek V4 Flash passed 16 of 19 scored expectations with the skill and 4 of 15 without it. One no-skill scenario errored after a permission request was rejected, so the aggregate denominators differ. On the four scenarios that ran in both conditions, the skill run passed 12 of 15 expectations and the no-skill run passed 4 of 15. The five prompts test planning, blocked-worker handling, escalation after repeated failures, migration ordering, and PR verification. This is preliminary evidence that the skill improved adherence to the written workflow on this small eval set. It is not a measure of live coordination or merge-conflict reduction. See the [benchmark summary](../skills/claude/herdr-orchestrator/evals/results/2026-10-01-opencode-deepseek-v4-flash/benchmark.md).

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

### Case study: a remote-identity contract crosses herds

In a separate October 4 evening exchange, an identity-service session reviewed its subject-token work and flagged that “chat identities” described the wrong concept. The owner chose “remote identities,” distinct from sign-in identities, with the stable key `{source, external_id}`. The identity orchestrator translated that decision into changes to the subject-token claim, API, database naming, client, and ADR work, then sent the contract to the policy-sync and gateway sessions.

The gateway orchestrator reports that it had already found and read the identity-service plan in the wiki while planning overlapping gateway work. When the rename arrived, it checked the catalog's `runtime:authenticate` implementation, found that it did not read the token's `ext` claim, and told the identity session no gateway change was needed. The identity handoff links the rename to merged `kei-oidc-bridge` PR #10; its ADR follow-up was open as `kei` PR #771 in the handoff summary.

This is a trace of context transfer, impact checking, and an explicit no-op decision. The transcripts and PR references make the sequence inspectable. This exchange happened after the October 4 snapshot window ended at 5 p.m., so it is a separate case study and is not included in that window's counts.

## Example: changing the encryption design without losing the history

A second example came from audit-log encryption. The initial design assumed a server-held key. A closer review exposed a mismatch with the actual goal: sensitive tool arguments should not be readable by the service. The design shifted to customer-held public keys and opt-in encryption, with digest-only records when no key is registered.

That decision affected catalog APIs, runtime behavior, the CLI, console UI, documentation, and the user-facing key-rotation flow. Rather than letting each worker infer the new design from chat, the orchestrator updated the shared contract and redirected the affected workers. The ADR recorded the rationale; separate workers could implement the catalog registry, runtime encryption, CLI, and UI against that contract. A later decision required users to acknowledge that key rotation affects future records while older records still need their original private keys.

The useful property here is not that the first design was right. It was not. The useful property is that the change was made durable, affected workers were identified, and the implementation was re-scoped before the old assumption spread further.

### Case study: Claude orchestrates an OpenCode worker

The identity-service transcript also records a direct cross-model workflow. A Claude orchestrator planned seven OpenCode workers, split between Qwen and DeepSeek, with each worker assigned a repo and a bounded layer. In this setup, the Qwen 3.8 and DeepSeek V4 Flash workers each had a 100K-token context window. That is ample room for a large brief, but it does not tell one isolated session what another session decided or where to find the current contract. The brief required workers to search the wiki and claim their scope before editing. One dependency was enforced at dispatch: the Qwen catalog worker started only after the identity API contract was captured in the wiki, and it was told to build its client against that contract.

For a completed example, the DeepSeek OpenCode worker resynced the identity-service repository in PR #3. The Claude orchestrator independently checked the tree, build, vet, and database integration tests. It found that the migration path needed correction, sent that specific fix back to the worker, then reran the suite against PostgreSQL after the worker updated the PR. The corrected PR passed and merged. This shows a cross-model task, review, and repair loop with a durable contract gate. The transcript also records worker stalls and re-scoping; those are execution observations, not a controlled comparison of model capability.

The wiki's role here is discovery and synchronization. A large context window can hold a lot once the right information is loaded. The wiki helps a separate session find the relevant decision, check whether it is current, and retrieve a focused handoff without replaying every prior conversation. The context-retention experiment tests that access and transfer benefit, not whether a wiki makes a model more capable.

A separate GW task export shows the same pattern with a Qwen OpenCode worker. The task brief specified the files, interfaces, tests, stack layers, and wiki searches. In the transcript, the worker ran four visible `wiki search` commands and captured a file-ownership claim; it also checked open PRs and found PR #91 touched the same allowlist file. It inspected the exact diff, then kept its changes away from the line changed by that PR. During implementation, a test exposed that `data-connectors/invoke` matched the generic CLI allowlist path and caused a runtime bearer to be rejected as an invalid CLI token. The worker added a focused regression test, changed the CLI middleware to skip runtime control-plane paths, and the full Go suite passed after that change.

The trace also shows why the workflow still needs review. A later extra layer added `PUT` for `credential-store/recipients` even though the worker's own catalog route search showed that endpoint only supports `GET`. The following stack PR also retained commits already squash-merged from lower layers and needed a rebase. The export ends with the owner requesting that rebase, so it does not document the repair's outcome. This is evidence that a detailed Claude-to-OpenCode brief and wiki searches supported implementation and diagnosis; it is also evidence that explicit contract checks, stack verification, and human review remain necessary. The export spans 10:10 a.m. to 9:11 p.m. on October 4, crossing the snapshot cutoff; count only events with timestamps inside the observation window when combining it with those results.

### Case study: make the reminder part of the workflow

An October 1 harness-policy session shows why a skill alone did not keep the wiki habit reliable. The orchestrator missed a cross-herd request that had been captured in the wiki for about seven minutes. It changed the recurring `/loop` checklist so each tick looked for claim requests addressed to that herd and answered them. The loop also checked for worker claims and PR handoffs, and compared open PR file changes against the herd's scopes. In a separate overlap, the wiki had no record of another herd's catalog PR; the orchestrator found it through GitHub, recorded the blocker and migration claim in the wiki, and revised its own bundle plan to extend the other team's contract instead of creating a competing one.

The same session exposed a retrieval problem: inbox search returned only a short snippet, not enough for a worker to use the full shared contract. The orchestrator supplied the contract directly and recorded the limitation for follow-up. This is useful evidence because it includes a miss, a workflow correction, and a wiki limitation. It suggests that durable memory needs both a good retrieval path and a recurring check that brings new information back into the active task.

## What this does and does not establish

The examples show coordination mechanisms operating across sessions: shared claims, contract changes, explicit dependencies, staged work, and worker acknowledgements. In my experience, merge conflicts have decreased since using this process. I have not collected a consistent baseline, conflict count, or denominator, so I cannot claim a measured reduction rate.

The completed observation window is **October 4, 2026, 10:28 a.m. to 5:00 p.m. Mountain Time**. The snapshot archive contains 14 inventories from 10:45 a.m. through 5:00 p.m.; after the initial 15-minute interval, they are approximately 30 minutes apart. The opening manual inventory found 2,020 wiki pages. At 10:45, the first snapshot reported 1,985 pages and four running Herdr sessions. It also captured the session report that 35 of 36 requested stale pages had been deleted with no failures; the visible `log.md` tail contains 35 page-deletion entries. The remaining requested page is not verified as deleted.

By 5:00 p.m., the wiki inventory reported 2,071 pages, an increase of 86 from the first collected inventory. Session inventories showed four named sessions early in the window, six around 2:00 p.m., and seven from 3:30 p.m. onward. Deduplicating the operation-log rows visible across the saved snapshot tails after the first snapshot yielded 62 capture entries and 73 page write/organize pairs. These are counts of entries visible in the retained tails, not a guaranteed complete count of every operation during the window. `log.md` dates entries but does not timestamp them to the half-hour.

The saved terminal excerpts are filtered and sometimes summarize multiple shell commands as one line. They do not provide a reliable count of `wiki search` or `wiki audit` calls, and `log.md` does not record those read operations. The snapshots therefore establish sustained, cross-session wiki activity, growth in the page inventory, and a verified deletion trail. They do not establish a complete command-use rate or a conflict-reduction rate.

### Experiments that would strengthen the finding

Two follow-up studies can test the remaining claims without changing the completed snapshot results:

1. **Live coordination and conflict study.** For each eligible overlap episode (two or more sessions changing the same repository, files, routes, API contract, or migration sequence), record whether a wiki search/read occurred, whether a claim or contract was found, whether the second session changed its scope or order before editing, and the resulting PR/rebase outcome. Define a conflict as a merge or rebase conflict requiring manual resolution; record incidence per eligible overlap episode and time to resolve. Compare matched episodes with and without a documented wiki-mediated adjustment, and report session count, changed-file overlap, stack use, and dependency complexity. Do not label a case “avoided conflict” unless the timeline shows the overlap, the coordination signal, the resulting change in work, and the later merge outcome. This observational design can show association and traced mechanisms; a causal claim would need repeated comparable work or a planned, randomized rollout.
2. **Cross-harness context-retention replay.** Select archived handoffs with a known downstream task and score them against a fixed rubric. Within each harness/model pair, give fresh, isolated runs either the raw transcript or the curated wiki/brief packet, then ask them to perform the same task. Include Claude-to-OpenCode handoffs, such as the identity API contract consumed by the Qwen catalog worker, and test more than one OpenCode model where available. Score preserved decisions and interface fields, missed constraints, stale or superseded assumptions, unnecessary rediscovery, and task correctness; also record time and token use. Randomize the order and keep graders blind to the condition. Report results by harness/model rather than treating models as interchangeable. The current skill benchmark is a useful pilot for procedural adherence, but it does not compare raw transcripts with curated cross-harness handoffs.
3. **Cadence-compliance replay.** Use a fixed multi-session scenario with a plan, worker dispatches, a newly captured contract change, and a later tick. Compare fresh runs with the same skill in two conditions: the skill alone, and the skill plus explicit `/plan` requirements and `/loop` checks. Score wiki search before dispatch, claim and handoff checks, detection of the new contract, timely relay to affected workers, and unnecessary nudges; repeat each condition several times with the same harness/model. This tests whether the planning and recurring reminders improve workflow adherence. Keep it separate from the conflict study: better protocol adherence does not by itself show fewer conflicts.

For both studies, record session and worker identifiers, harness/model, timestamps, PR links, wiki operation type, and the decision or contract IDs involved. Keep query content and private conversation text out of shared metrics unless needed for the case review; use redacted excerpts and stable event IDs. This makes search/read counts and cross-session handoffs measurable while limiting collection to what the analysis needs.

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
