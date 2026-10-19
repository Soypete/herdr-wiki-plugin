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
wiki audit [--json] [--stale-days N]
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
