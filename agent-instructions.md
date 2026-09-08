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
  `wiki search <query> [--top-k N] [--json]`
- **When you learn something durable**, capture it:
  `wiki capture --title "..." --type claim --content "..." [--link predicate:target]`
- **Stats:** `wiki stats`
- **Reconcile the inbox into the graph** (usually a human does this, not you):
  `wiki organize`

Rules:
- `--type` must be one of: `claim`, `contradiction`, `decision`, `entity`,
  `source`.
- Link `predicate` must be one of: `derived_from`, `contradicts`, `supports`,
  `about`, `relates_to`.
- Invalid types/predicates are rejected — do not guess or coerce a value.
- Captures land in an inbox; do **not** edit wiki pages directly.
- If `wiki` is not on PATH, run
  `python3 /path/to/herdr-wiki-plugin/bin/wiki <args>`.
