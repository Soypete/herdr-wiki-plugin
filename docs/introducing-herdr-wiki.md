# Herdr Wiki: 19x your output for no reason

Want to 19x your output for no reason? Same. The 19x is a joke; the context loss is real. Terminal agents keep rediscovering work that another session already did.

I run coding agents in separate terminal sessions. They each have their own transcript, task plan, and local view of the code. One session finds the right API contract; another starts from scratch. One decides to hold a risky rollout; another sees an old status and charges ahead. Parallelism creates workers quickly. Shared context takes deliberate work.

That became obvious during a planned maintenance window. I was preparing to roll out a change that could disrupt production. The orchestrators had been coordinating through a shared wiki, recording decisions, handoffs, and status so other sessions could find them. As the rollout got time-sensitive, Claude Code sessions also began sending direct messages over a local Unix socket. The `uds:` peer address in the transcript matches Claude Code's documented [cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging). Claude Code also has [agent teams](https://code.claude.com/docs/en/agent-teams), which coordinate independent sessions around shared tasks.

Those native Claude features are useful for live coordination inside Claude Code. The wiki handles the durable handoff. It preserves the decision and its source after a session ends, makes it available to Codex and OpenCode, and lets me keep working when Claude Code runs out of session credits. Messaging moves a note between active sessions. The wiki carries the context across tools and time.

## A wiki from the terminal

Herdr Wiki is a Herdr plugin for developers who already work in terminal panes. Select text in a pane and capture it as a note. Search the shared wiki from another pane or agent session. Capture records land in an inbox with their source information, appear in search immediately, and can be organized into linked Markdown pages when you are ready.

The two main keybindings are simple:

- `prefix+w` searches the wiki, using selected text as the query when available.
- `prefix+W` captures selected text with a title, note type, and optional links.

The same `wiki` CLI and agent skills are available to Claude Code, Codex, and OpenCode. A human can capture a decision from a pane; an agent can search before changing a shared interface; either can add a handoff with links to the decisions it depends on. They use the same wiki root and capture protocol.

The capture flow keeps the source attached to the note. Captures enter a shared inbox and are searchable before organization. A deliberate organize step turns accepted captures into interlinked pages. Search stays read-only, and one organizer writes to the wiki graph. You choose what deserves to persist; the plugin does not vacuum up every conversation or every file.

That provenance matters when the note changes what an agent does. A rollout decision should point to the message or record that motivated it, who made it, when it changed, and what happened after. “Hold the deploy” is a useful status. A linked decision and verified outcome are a record another session can trust and inspect. The broader idea is described in this [AI data provenance overview](https://nhimg.org/glossary/ai-data-provenance/).

## Install it

```sh
herdr plugin install Soypete/herdr-wiki-plugin
```

Herdr Wiki requires Herdr 0.7.5 or later, Python 3.10 or later, and a wiki directory. The default is `~/code/wiki`; set `WIKI_PATH` to use another location. The plugin has no runtime Python dependencies.

The 19x is the joke. The bonus output comes from not making every new session rediscover the same decisions. Capture it once, point the next worker to it, and keep going in another harness when this session runs out of credits. That’s a pretty good deal for a wiki you can reach from a terminal pane.
