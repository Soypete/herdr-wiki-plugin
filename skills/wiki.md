# Wiki Skill

Search and capture in the personal LLM-Wiki knowledge base from within your
agent context. This is the agent-facing counterpart to the herdr plugin's
human search popup — you run a command and read the results.

## Usage

```
/wiki <query> [--top-k N] [--json]
/wiki stats
/wiki capture --title T --type T --content C [--link predicate:target ...]
/wiki organize
```

## Examples

```
/wiki whitepaper
/wiki memory indexing --top-k 5
/wiki whitepaper --json
/wiki stats
/wiki capture --title "finding" --type claim --content "..." --link derived_from:imported/whitepaper
```

## Options

- `<query>` — search term (a bare first argument is treated as a search)
- `--top-k N` — number of results (default 10)
- `--json` — machine-readable output
- `stats` — wiki statistics
- `capture` — write a note to the inbox (types/predicates must be in the
  closed vocabulary; invalid values are rejected)
- `organize` — reconcile the inbox into wiki pages

## When to use it

- Before answering, search the wiki for prior notes/claims about the topic.
- When you learn something durable, capture it so it becomes part of the
  knowledge base (a human runs `organize` to fold it into the graph).

Wiki location: `~/code/wiki` (override with `WIKI_PATH`).
