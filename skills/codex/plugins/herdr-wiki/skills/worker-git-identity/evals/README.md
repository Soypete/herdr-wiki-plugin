# worker-git-identity evals

Eval cases for the worker-git-identity skill template, portable across all
three harnesses (Claude Code, Codex, opencode). The prompts use example
values (`acme`, `acme-swarm-bot`, `bot-gh`) so they run against the template
without filling in the placeholders.

## Run

From the repo root:

```sh
node scripts/run-evals.mjs --skill worker-git-identity --harness claude --out evals-out/worker-git-identity-<date>
```

The runner calls models, so it is not part of the pytest suite. Grading uses
`claude -p` (the Claude Code CLI).

These files are the answer key. Leave `evals/` out when you copy the skill
into a harness's skills directory.
