<!--
Paste the block below into your project's CLAUDE.md (for Claude Code) and/or
AGENTS.md (for Codex and other agents that read the AGENTS.md standard).
This puts the wiki commands in the agent's context at session start, so it
knows how to use them without any skill/plugin mechanism.
-->

## Wiki (personal knowledge base)

You have a `wiki` command for a personal LLM-Wiki knowledge base. It prints
results to stdout, so run it and read the output.

- **Before answering** about a topic, search for prior notes/claims:
  `wiki search <query> [--top-k N] [--no-inbox] [--json]`
  Search includes pending inbox records (another agent's unorganized
  captures) by default, marked `inbox:`; pass `--no-inbox` to see only
  settled wiki pages.
- **When you learn something durable**, capture it:
  `wiki capture --title "..." --type claim --content "..." [--link predicate:target]`
- **Before writing code**, search for the conventions that bind the work and
  follow the pages they return — the page is authoritative, not memory:
  - `wiki search "package placement conventions"` — pkg/database boundary,
    repository shape
  - `wiki search "commit and pr shape"` — granular commits, one per PR by default
  - `wiki search "duplicate handler implementations"` — check what is actually
    wired before hardening it
- **Stats:** `wiki stats`
- **Reconcile the inbox into the graph** (usually a human does this, not you):
  `wiki organize`
- **Audit wiki health** (find orphans, broken links, stale inbox, unindexed
  pages, empty pages): `wiki audit [--json] [--stale-days N]`
- **Delete a wiki page or inbox record** (exact match required — no globbing):
  `wiki delete page <path>` or `wiki delete inbox <id>`

Rules:
- `--type` must be one of: `claim`, `contradiction`, `decision`, `entity`,
  `source`, `blocker`, `handoff`, `ack`, `release`, `contract_change`.
- Link `predicate` must be one of: `derived_from`, `contradicts`, `supports`,
  `about`, `relates_to`, `answers`, `acknowledges`, `blocks`.
- Invalid types/predicates are rejected — do not guess or coerce a value.
- Captures land in an inbox; do **not** edit wiki pages directly. Search is
  read-only on the inbox — only a human's `wiki organize` changes it.
- If `wiki` is not on PATH, run
  `/path/to/herdr-wiki-plugin/bin/wiki <args>`.
