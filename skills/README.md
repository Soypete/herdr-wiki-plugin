# Agent skills

The wiki is available to agents in three ecosystems. All of them delegate to
the same `wiki` command (the `haikei_wiki` CLI), so behavior is identical
everywhere.

## One-time setup: put `wiki` on PATH

Every skill calls the `wiki` launcher. Symlink it onto PATH once:

```
ln -s "$(pwd)/bin/wiki" ~/.local/bin/wiki
```

(`~/.local/bin` is on PATH by default.) Verify:

```
wiki stats
```

The launcher resolves the repo from its own location, so it works from any
directory and via the symlink.

## opencode

Skill lives at `skills/wiki.md` + `skills/wiki.py` (discovered from the
`skills/` dir). Allow it in `opencode.json`:

```json
{ "permission": { "skill": { "wiki": "allow" } } }
```

Then in an opencode session: `/wiki whitepaper`, `/wiki stats`, …

A bare first argument is treated as a search, so `/wiki <query>` just works.

## Claude Code

Copy the skill to your user or project skills dir:

```
mkdir -p ~/.claude/skills/wiki
cp skills/claude/wiki/SKILL.md ~/.claude/skills/wiki/SKILL.md
```

Claude picks it up automatically; it runs `wiki <args>` from its shell.

## Codex

The skill ships as a Codex plugin + local marketplace (`skills/codex/`).
Install it:

```
codex plugin marketplace add /path/to/herdr-wiki-plugin/skills/codex
codex plugin add herdr-wiki --marketplace herdr-wiki
```

Verify:

```
codex plugin list | grep herdr-wiki
```

It registers the `wiki` skill, which runs `wiki <args>`.

## The commands (all agents)

```
wiki search <query> [--top-k N] [--json]
wiki stats
wiki capture --title T --type T --content C [--link predicate:target ...]
wiki organize
```
