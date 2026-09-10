---
name: wiki
description: Search and capture in the personal LLM-Wiki knowledge base. Use when the user asks to search the wiki, recall prior notes/claims/decisions, look up something previously captured, or capture a durable finding into the knowledge base.
---

# Wiki

Query and write to the personal LLM-Wiki knowledge base. All operations go
through the `wiki` command, which prints results to stdout so you can read
them in your context.

## Commands

```
wiki search <query> [--top-k N] [--no-inbox] [--json]
wiki stats
wiki capture --title T --type T --content C [--link predicate:target ...]
wiki organize
```

## Examples

```
wiki search whitepaper
wiki search "memory indexing" --top-k 5
wiki search whitepaper --json
wiki search coord/claim --no-inbox
wiki stats
wiki capture --title "finding" --type claim --content "..." --link derived_from:imported/whitepaper
```

## How to use it

- **Before answering**, search the wiki for prior notes/claims about the
  topic: `wiki search <topic>`.
- **When you learn something durable**, capture it:
  `wiki capture --title "..." --type claim --content "..."`.
- Use `--json` on `search` when you need to parse results programmatically.

## Rules

- `--type` and link `predicate` must come from the closed capture vocabulary
  (`claim`, `contradiction`, `decision`, `entity`, `source`, `blocker`,
  `handoff`, `ack`, `release`, `contract_change`; predicates `derived_from`,
  `contradicts`, `supports`, `about`, `relates_to`, `answers`, `acknowledges`,
  `blocks`). Invalid values are rejected — do not guess or coerce a type.
- Search surfaces **pending inbox records** (marked `inbox:`) alongside wiki
  pages by default, so you see another agent's unorganized captures; pass
  `--no-inbox` to see only settled pages. Search never modifies the inbox.
- Captures land in an inbox; a human runs `wiki organize` to fold them into
  the interlinked graph. Do not edit wiki pages directly.
- If `wiki` is not on PATH, run the launcher from the plugin repo:
  `python3 /path/to/herdr-wiki-plugin/bin/wiki <args>`.
