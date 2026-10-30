---
name: wiki
description: Search and capture in the personal LLM-Wiki knowledge base. Use before Herdr coding and orchestration tasks to retrieve shared plans, decisions, contracts, blockers, and handoffs; also for wiki lookup and durable capture.
---

# Wiki

Query and write to the personal LLM-Wiki knowledge base. All operations go
through the `wiki` command, which prints results to stdout so you can read
them in your context.

## Commands

```
wiki search <query> [--top-k N] [--no-inbox] [--json]
wiki show <page> [--json]
wiki stats
wiki capture --title T --type T --content C [--link predicate:target ...]
wiki organize [--daemon]
wiki plan status|active|complete|interrupt|archive <page>
wiki audit [--json] [--stale-days N] [--structural] [--collisions [--repo R]]
wiki claim --repo owner/name --paths GLOBS [--branch B] [--pr N] [--owner ID] [--expires E]
wiki claims [--repo R] [--paths GLOBS] [--json]
wiki release <claim-id>
wiki reserve --repo owner/name --kind KIND --value VALUE [--owner ID]
wiki supersede <page> --by <page-or-url> [--reason "..."]
wiki withdraw <page> --reason "..."
wiki delete page <path>
wiki delete inbox <id>
```

## Examples

```
wiki search whitepaper
wiki search "memory indexing" --top-k 5
wiki search whitepaper --json
wiki search coord/claim --no-inbox
wiki show decision/draft-adr
wiki show inbox:20261001T144448933485-abcd
wiki stats
wiki capture --title "finding" --type claim --content "..." --link derived_from:imported/whitepaper
wiki audit
wiki audit --json
wiki claim --repo HaikeiLabs/kei-cli --paths "internal/app/*.go" --branch feat/x --pr 123 --owner gc-1 --expires 7d
wiki claims --repo HaikeiLabs/kei-cli
wiki reserve --repo HaikeiLabs/kei-policy-catalog --kind migration --value 173 --owner pm-1
wiki audit --collisions --repo HaikeiLabs/kei-cli
wiki delete page wiki/claim/indexed-retrieval-wins.md
wiki delete inbox rec-1
```

## How to use it

- **Before coding**, search the wiki for relevant plans, decisions, contracts, blockers, and handoffs. Then use targeted `rg` against relevant source paths to verify current code. An empty wiki result is valid.
- **Before answering**, search the wiki for prior notes/claims about the
  topic: `wiki search <topic>`.
- **Before completion**, capture a task-linked handoff with wiki queries, atomic commits, tests, PR URL, and unfinished work; dependent PRs use `gh stack`.
- **When you learn something durable**, capture it:
  `wiki capture --title "..." --type claim --content "..."`.
- Use `--json` on `search` when you need to parse results programmatically.
- Read full pages with `wiki show <page>` (or `wiki show inbox:<id>` for a pending
  inbox record) — never read wiki files with a file tool; it triggers
  external-directory permission prompts in scratch worktrees. `--json` returns
  `{path, title, category, created, content, links}`.

## Claims and reservations (every worker does this)

A worker coordinates in exactly two ways: **claims** and **captures**. It does
not message other workers and does not decide ordering; the orchestrator watches
for collisions and tells the worker what to do (chain, wait, renumber).

**Claim the paths you edit.** Before touching shared paths, look, claim, and release:

```
wiki claims --repo HaikeiLabs/kei-cli --paths "internal/app/*.go"      # who holds these right now?
wiki claim  --repo HaikeiLabs/kei-cli --paths "internal/app/*.go,README.md" \
            --branch feat/x --pr 123 --owner <your-worker-name> --expires 7d
wiki release <claim-id>                                                 # when the PR merges or you stop
```

- Use the real PR number and branch once they exist; update the claim if your file set grows.
- Claims **expire after 24 hours by default** (`--expires`, e.g. `7d`); a lapsed claim is inactive. Set `--expires` to cover the life of the PR, and re-claim if it lapses.
- An overlap with someone else's claim is not yours to resolve: capture a `blocker` or tell the orchestrator and wait for its instruction.

**Reserve ordered resources.** Use `wiki reserve` for any sequence where two branches
can pick the same value: database migration numbers, eval-case ids, schema versions.

```
wiki claims --repo HaikeiLabs/kei-policy-catalog                       # reservations show up next to claims
git ls-tree --name-only origin/main migrations/ | tail -3              # the base branch's current maximum
wiki reserve --repo HaikeiLabs/kei-policy-catalog --kind migration --value 173 --owner <your-worker-name>
```

1. **Look first.** Read the existing reservations (`wiki claims --repo R`) and the base branch's current maximum.
2. **Reserve the next free value above both**, before you write the file. Match the repo's zero-padding (`--value 074` if files are `074_*.sql`).
3. `reserve` does **not refuse** a value that is already taken: it records yours and the clash shows up afterwards as a `reservation_conflict` in `wiki claims` and `wiki audit --collisions`. So re-run `wiki claims --repo R` right after reserving; if your value collides, reserve the next free one and release the other (`wiki release <id>`).
4. Name the file with the reserved value. Re-check the base branch's maximum right before you mark the PR ready; if main moved to or past your value, reserve a new one and release the old.
5. Release the reservation when the PR merges or is abandoned.

Gaps are normally fine; the repo's own CI guard is the authority on what is legal. A reservation is
coordination, not enforcement.

**Capture, do not narrate.** Record durable facts with `wiki capture` (types: `claim`, `decision`,
`blocker`, `handoff`, `ack`, `contract_change`): a handoff at every status change and at the end, a `blocker`
when you cannot proceed, a `contract_change` when you change something other workers or repos consume.

## Conventions to read before writing code

Run these three searches at the start of any task and follow the pages they
return — the wiki page is authoritative, not your memory of it:

```
wiki search "package placement conventions"        # pkg/database boundary, repository shape
wiki search "commit and pr shape"                  # granular commits, one per PR by default
wiki search "duplicate handler implementations"    # check what is actually wired before hardening
```

- Delete requires an exact path or id — no glob/regex patterns. Deletions
  are logged in log.md; inbox records are moved to inbox/deleted/.

## Rules

- `--type` and link `predicate` must come from the closed capture vocabulary
  (`claim`, `contradiction`, `decision`, `entity`, `source`, `blocker`,
  `handoff`, `ack`, `release`, `contract_change`; predicates `derived_from`,
  `contradicts`, `supports`, `about`, `relates_to`, `answers`, `acknowledges`,
  `blocks`). Invalid values are rejected — do not guess or coerce a type.
- Search surfaces **pending inbox records** (marked `inbox:`) alongside wiki
  pages by default, so you see another agent's unorganized captures; pass
  `--no-inbox` to see only settled pages. Search never modifies the inbox.
- Session plans have a lifecycle: `wiki plan status` lists active/interrupted plans with open tasks — the takeover surface for a new session; `wiki plan complete|interrupt|archive` moves them along.
- Captures land in an inbox; a scheduled single-writer runner (`wiki organize --daemon`, launchd every 15 min) or a human `wiki organize` folds them into
  the interlinked graph. Do not edit wiki pages directly.
- If `wiki` is not on PATH, run the shell launcher directly from the plugin repo:
  `/path/to/herdr-wiki-plugin/bin/wiki <args>`.
