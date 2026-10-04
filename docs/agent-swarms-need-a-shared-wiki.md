# Agent swarms need a shared wiki

*How I use Herdr, a shared LLM-Wiki, and small operating rules to keep parallel coding agents from losing the plot.*

Parallel agents are easy to start. Keeping them pointed at the same reality is the hard part.

I run Claude Code, Codex, and OpenCode in separate Herdr sessions. Each orchestrator has workers, its own task breakdown, and its own view of the code. When one session learns something the others need, that information can disappear into a transcript. Then an agent repeats the research, edits a file another worker owns, or builds against an interface that has changed.

I started using a shared wiki as the durable memory between these sessions. Herdr gives the agents their workspaces and panes. The wiki gives each orchestrator a place to search for prior decisions, ownership claims, blockers, and interface changes. Harness-specific skills teach the same basic protocol in Claude Code, Codex, and OpenCode.

The capture flow is useful because another session can see a new note before it has been folded into the wiki's organized pages. A capture lands as JSON in a shared inbox and is immediately searchable with an `inbox:` label. Search doesn't mutate it; a single organize step turns accepted captures into linked pages. Deletions are recorded in `log.md`, which gives us a way to verify what was actually removed instead of counting a request as an action.

Search itself is straightforward text retrieval: it scans wiki pages and the index case-insensitively, and includes pending inbox records by default. Title matches rank above body matches, and superseded records remain searchable but are down-ranked. That makes the system easy to inspect, while reminding me to use the terms another session is likely to search for.

The protocol is practical: search before changing shared code; give each worker a narrow brief with explicit files and a done condition; capture decisions and contract changes; tell affected workers to read them; and put dependent PRs into a stack with one owner. Quick nudges stay in the worker's pane. Information the next worker will need goes in the wiki.

I also learned that having a skill is not enough to keep the habit alive through a long effort. In Claude Code, I use `/plan` to make wiki searches, ownership, and worker capture requirements part of the plan before dispatch. Then `/loop` makes the orchestrator revisit the wiki on each recurring tick, find new claims or contract changes, and nudge the workers whose tasks they affect. Without that cadence, I can watch the agents work and still forget to remind them to use the shared memory. The slash commands help me remember; the wiki gives all the sessions somewhere durable to find the same information.

I saw this pay off when two herds were changing the same service family. One was moving catalog and console handlers out of root packages. Another was consolidating the API gateway and changing routes. Their orchestrators checked claims and compared scope before dispatching the next layer. They agreed the gateway team would start with catalog route groups outside the cleanup stack, then wait on overlapping route groups until the cleanup merged. They named the routes the runtime depended on, preserved the console's audit-encryption paths, and left a CLI version pin with its current owner.

That exchange changed the sequence before it became a merge conflict. It also gave workers in either harness a place to find the decision. The gateway workers were told to check the wiki for contract changes before editing routes and to rebase after upstream changes landed.

Another useful moment came when our audit-encryption design changed. We realized the first server-held-key proposal did not match the goal of keeping sensitive tool arguments unreadable to the service. The design moved to optional, customer-held encryption, with digest-only records when no key is configured. That decision touched the catalog, runtime, CLI, UI, and docs. Putting the decision and contract in the wiki let each worker adjust against the same revised design instead of reconstructing it from a long chat history.

This is not a claim that the wiki prevents all conflicts. I have seen fewer merge conflicts, but I have not measured the before-and-after rate. To do that responsibly, I’d need a baseline and consistent counts across PRs, rebases, overlapping file changes, and work redirected after a contract update. Session histories could help explain how agents surfaced and acted on coordination signals, but anecdotes are not a metric.

What I can say is that the process makes dependencies and decisions easier to find. Stacked PRs expose code order. Wiki claims expose ownership across sessions. Contract-change notes tell workers what moved. Skills define the procedure, while `/plan` and `/loop` help me keep applying it over time. Together they reduce the chance that each new orchestrator invents a different process or lets a worker proceed with stale context.

The goal is not to maximize the number of agents running at once. The goal is to get useful work to review without making every session rediscover the same constraints. Agent swarms need shared memory, and they need simple instructions for keeping it current. A wiki is a surprisingly good place to start.

*For the longer architecture and workflow, see [A Shared Wiki for Agent Swarms](agent-swarm-coordination-whitepaper.md).*
