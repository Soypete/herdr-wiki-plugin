# Agent skills

This repo ships skills for two agents that work together:

- [**wiki**](#wiki) — search and capture in the herdr wiki knowledge base.
- [**herdr-orchestrator**](#herdr-orchestrator) — orchestrate parallel coding
  work across herdr worker agents (policy layer over the base herdr skill).

A third skill, [**worker-git-identity**](#worker-git-identity), is a template
for having workers commit, push and open PRs as a bot account instead of you.

All skills are available for three harnesses: Claude Code, Codex (plugin), and
opencode. All copies are byte-identical (verified by `tests/test_skill_drift.py`).

herdr-orchestrator is a **policy layer** over the base herdr skill. It requires
`herdr` (installed and running) plus the `wiki` CLI (`haikei_wiki`) from this
plugin; without both it stops with a clear error.

---

## wiki

The wiki skill is available to agents in three ecosystems. All of them delegate
to the same `wiki` command (the `haikei_wiki` CLI), so behavior is identical
everywhere.

### One-time setup: put `wiki` on PATH

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

### opencode

The skill is a standard OpenCode skill at `.opencode/skills/wiki/SKILL.md`
(discovered when OpenCode runs in this repo). The repo's `opencode.json`
already allows it:

```json
{ "permission": { "skill": { "wiki": "allow" } } }
```

To use it in another project, copy the skill and the permission:

```
mkdir -p .opencode/skills/wiki
cp /path/to/herdr-wiki-plugin/.opencode/skills/wiki/SKILL.md .opencode/skills/wiki/
```

and add `permission.skill.wiki = allow` to that project's `opencode.json`.
Then in an opencode session the agent can run `wiki search <query>`,
`wiki stats`, …

### Claude Code

Copy the skill to your user or project skills dir:

```
mkdir -p ~/.claude/skills/wiki
cp skills/claude/wiki/SKILL.md ~/.claude/skills/wiki/SKILL.md
```

Claude picks it up automatically; it runs `wiki <args>` from its shell.

### Codex

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

### Alternative: `CLAUDE.md` / `AGENTS.md` (no skill needed)

If you don't want to set up a skill/plugin, put the commands in the agent's
instruction file instead — it's read at session start, so the agent always
knows the wiki exists:

- **Claude Code** → paste into your project's `CLAUDE.md`
- **Codex** (and most other agents) → paste into your project's `AGENTS.md`

The ready-to-paste block is in [`../agent-instructions.md`](../agent-instructions.md).

### The commands (all agents)

```
wiki search <query> [--top-k N] [--no-inbox] [--json]
wiki stats
wiki capture --title T --type T --content C [--link predicate:target ...]
wiki organize
wiki audit [--json] [--stale-days N]
wiki delete page <path>
wiki delete inbox <id>
```

Search includes pending inbox records by default (marked `inbox:` in results)
so agents can see each other's unorganized captures; `--no-inbox` limits the
search to settled wiki pages. Search never modifies the inbox.

`wiki audit` is read-only: scans for orphans, broken links, unindexed pages,
empty pages, and stale inbox records. `wiki delete` requires an exact path or
id — no glob/regex patterns — and logs all deletions in log.md. Inbox records
are moved to `inbox/deleted/` (not permanently removed).

---

## herdr-orchestrator

The herdr-orchestrator skill orchestrates parallel coding work across herdr
worker agents (Codex, Claude Code, opencode). It is a **policy layer** over
the base herdr skill: it handles decomposition, scaffolding, watching, nudging,
failure handling, and wiki-based coordination.

**Prerequisites:**

1. `herdr` installed and running (`herdr agent` works).
2. The `wiki` CLI from this plugin on PATH (see [wiki setup](#one-time-setup-put-wiki-on-path)).
3. `gh stack` if the repo uses stacks (optional fallback to `gh pr create`).

### opencode

The skill is at `.opencode/skills/herdr-orchestrator/SKILL.md` (auto-discovered
when opencode runs in this repo). The repo's `opencode.json` allows it:

```json
{ "permission": { "skill": { "herdr-orchestrator": "allow" } } }
```

To use it in another project, copy the whole skill directory and add the
permission:

```
mkdir -p .opencode/skills/herdr-orchestrator
cp -R /path/to/herdr-wiki-plugin/.opencode/skills/herdr-orchestrator/ .opencode/skills/herdr-orchestrator/
```

Then add `"herdr-orchestrator": "allow"` to that project's `opencode.json`
under `permission.skill`.

### Claude Code

Copy the skill directory to your user or project skills dir:

```
mkdir -p ~/.claude/skills/herdr-orchestrator
cp -R skills/claude/herdr-orchestrator/ ~/.claude/skills/herdr-orchestrator/
```

Claude picks it up automatically. The orchestrator runs `herdr`, `wiki`, and
`gh` from its shell.

### Codex

The skill ships inside the same `herdr-wiki` plugin that provides the wiki
skill. If you have already installed the plugin (see [Codex](#codex-1) under
wiki), the herdr-orchestrator skill is available automatically — no additional
installation needed. The plugin's `skills/` directory contains both `wiki/`
and `herdr-orchestrator/`.

---

## worker-git-identity

A **template** skill that teaches workers to commit, push and open pull
requests as a dedicated bot GitHub account, so you can formally approve their
PRs and protect `main` with code-owner review. It ships a `gh` wrapper
(`scripts/worker-gh`) that hands the bot's token to `gh` as `GH_TOKEN` from a
0600 file, and a debugging table for the usual traps (the shared macOS keyring
slot, Apple git's `osxkeychain` helper, global `insteadOf` rewrites to SSH,
`git config --local` in linked worktrees).

Set up the bot account, team, token and branch protection first:
[**Setting up a worker identity**](../docs/setting-up-a-worker-identity.md).
Then fill in the placeholders (`<BOT_USER>`, `<BOT_ID>`, `<ORG>`,
`<TOKEN_FILE>`, `<WRAPPER_NAME>`) in your installed copy.

| Harness | Source in this repo | Install |
| --- | --- | --- |
| Claude Code | `skills/claude/worker-git-identity/` | copy to `~/.claude/skills/worker-git-identity/` (without `evals/`) |
| opencode | `.opencode/skills/worker-git-identity/` | already allowed in this repo's `opencode.json`; elsewhere copy it and add `"worker-git-identity": "allow"` |
| Codex | `skills/codex/plugins/herdr-wiki/skills/worker-git-identity/` | ships in the `herdr-wiki` plugin (see [Codex](#codex)) |
