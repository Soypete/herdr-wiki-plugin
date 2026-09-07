# herdr-wiki-plugin

A [Herdr](https://herdr.dev) plugin that turns any Herdr pane into a capture
point for a personal [LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
knowledge base. Select text in a pane and capture it as a provenance-tagged
note; search the wiki from anywhere; reconcile the inbox into interlinked
markdown pages.

Self-contained: it vendors the `LLMWikiAdapter` storage layer, so
`herdr plugin install` works with no other setup.

## Requirements

- Herdr `>= 0.7.5`
- `python3` (3.10+) on `PATH`
- A wiki directory (default `~/code/wiki`; override with `WIKI_PATH`)

No Python dependencies are required at runtime. `watchdog` is used only if
you enable the (optional, unused-by-default) file watcher.

## Install

```
herdr plugin install Soypete/herdr-wiki-plugin
```

Or link a local checkout while developing:

```
git clone https://github.com/Soypete/herdr-wiki-plugin
herdr plugin link /path/to/herdr-wiki-plugin
```

Verify it registered:

```
herdr plugin list
herdr plugin action list --plugin haikei.wiki
```

## How to run it

### Keybindings

| Keys | Action |
| --- | --- |
| `prefix+w` | **Search** — opens an 80%-width popup. Uses the selected text as the query when available, otherwise you type it. |
| `prefix+W` | **Capture** — opens an 80%-width capture popup: shows provenance, pre-fills content from the selection, asks for a title, an entity type from the vocabulary (no default), and optional links. |

`prefix` is `ctrl+b` by default (see your Herdr `[keys]` config).

> Note: the default Herdr `workspace_picker` is also bound to `prefix+w`. If
> the two conflict, rebind one in your Herdr config, e.g.
> `[keys] workspace_picker = "prefix+p"`.

### Actions (CLI)

```
herdr plugin action invoke haikei.wiki.search        # open the search popup
herdr plugin action invoke haikei.wiki.capture       # open the capture popup
herdr plugin action invoke haikei.wiki.organize      # reconcile inbox -> wiki
herdr plugin action invoke haikei.wiki.context-dump  # debug: print plugin env + provenance
```

### Drive a capture from a pane (non-interactive)

The capture popup runs non-interactively when these env vars are set — this
is how captures are scripted from a pane:

```
herdr plugin pane open --plugin haikei.wiki --entrypoint capture \
  --env WIKI_CAPTURE_TITLE="my note" \
  --env WIKI_CAPTURE_TYPE=claim \
  --env WIKI_CAPTURE_CONTENT="the content to capture" \
  --env WIKI_CAPTURE_LINKS="derived_from:imported/some-page"
```

`WIKI_CAPTURE_LINKS` is `predicate:target;predicate:target`.

### The capture → organize flow

1. **Capture** (`prefix+W`) writes one atomic JSON file to `<wiki>/inbox/`
   and one line to `<wiki>/log.md`. It never touches the wiki graph.
2. **Organize** (`herdr plugin action invoke haikei.wiki.organize`) is the
   single writer to the graph: it turns each inbox record into a page under
   `<wiki>/wiki/<type>/`, updates `<wiki>/index.md`, appends to `log.md`, and
   moves the record to `inbox/processed/` (or `inbox/rejected/`).

Run organize whenever you want pending captures folded into the wiki.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| Wiki root | `WIKI_PATH` env var | `~/code/wiki` |
| Capture vocabulary | `$HERDR_PLUGIN_CONFIG_DIR/tbox.toml` | seeded from `haikei_wiki/starter_tbox.toml` on first run |

Find your config dir with:

```
herdr plugin config-dir haikei.wiki
```

### The closed capture vocabulary

Entity types and link predicates are enforced at the write boundary from
`tbox.toml`. A capture whose type or predicate is not in the file is
**rejected** with the violated constraint named — nothing is normalized or
coerced to a default. The organizer only proposes types from the loaded
vocabulary; it never invents new ones.

Starter entity types: `source`, `claim`, `entity`, `contradiction`,
`decision`. Starter link predicates: `derived_from`, `contradicts`,
`supports`, `about`, `relates_to`.

The file is a pure config artifact, shaped like a minimal T-box, so it can
later be replaced by a proper capture T-box (a `.ttl`) without changing plugin
code. To add a type or predicate, edit `tbox.toml` — that is a human decision.

## Provenance

Each capture records where it came from, read from
`HERDR_PLUGIN_CONTEXT_JSON`: `workspace`, `workspace_label`, `tab`, `pane`,
`agent`, and `selected_text` (when selected). Worktree provenance is resolved
via `herdr worktree list --workspace <id>` (the context JSON carries no
worktree field).

## Repo layout

```
herdr-plugin.toml        # Herdr manifest (actions, panes, keybindings)
bin/                     # thin entrypoints Herdr launches
haikei_wiki/             # the logic package (testable)
  vocabulary.py          # closed-vocabulary loader + write-boundary checks
  context.py             # HERDR_PLUGIN_CONTEXT_JSON -> provenance
  capture.py             # atomic inbox writer + log append
  organizer.py           # single-writer inbox -> wiki reconciliation
  herdr.py               # $HERDR_BIN_PATH helper
  adapter.py             # vendored LLMWikiAdapter (storage layer)
  interfaces.py          # vendored shared dataclasses
  starter_tbox.toml      # PROVISIONAL starter vocabulary
tests/                   # pytest suite (15 tests)
```

## Development

```
herdr plugin link /path/to/herdr-wiki-plugin
herdr plugin action list --plugin haikei.wiki

cd tests && python3 -m pytest -v
```

## License

MIT — see [LICENSE](LICENSE).
