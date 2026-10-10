---
name: worker-git-identity
description: Template for making herdr worker agents commit, push and open pull requests as a dedicated bot GitHub account (<BOT_USER>) instead of the human owner, and for debugging that setup without ever revealing its token. Covers per-worktree git author config, a gh wrapper script (<WRAPPER_NAME>) that exports GH_TOKEN from an owner-written 0600 token file instead of using the shared macOS keyring slot, the HTTPS-only push command with the wrapper as the git credential helper, draft PRs, and a symptom → cause → fix table (403 on push or PR create, workflow files rejected, commits showing the owner, SSH or password-manager prompts, the shared keyring slot that makes the owner's gh act as the bot, an expired token). Use this whenever a worker agent is about to commit, push or open a PR as the swarm's bot identity, whenever someone mentions the bot user, the wrapper, GH_CONFIG_DIR, GH_TOKEN or the workers team, or when a worker push or PR fails with 403, "Permission denied", "Write access to repository not granted" or "Author identity unknown", even if they never say "identity". Fill in the placeholders before installing.
---

# Worker git identity (template)

Worker agents commit, push and open pull requests as a bot account,
**<BOT_USER>**, not as the owner. That keeps human review meaningful: the
owner reviews the bot's PRs with a formal **Approve**, and GitHub does not
let a PR's author approve their own PR. If the owner's account authored every
worker PR, there would be no approval to give and no way to require one.

Everything here is plain `git`, `gh` and one POSIX shell script
(`scripts/worker-gh`), so it works the same from Claude Code, Codex or
opencode.

## Before you install: fill in the placeholders

This skill is a template. Replace every placeholder in this file and in
`scripts/worker-gh`, and rename the script to `<WRAPPER_NAME>`:

| Placeholder | Meaning | Example |
|---|---|---|
| `<BOT_USER>` | The bot's GitHub login | `acme-swarm-bot` |
| `<BOT_ID>` | The bot's numeric GitHub user id (`gh api users/<BOT_USER> -q .id`) | `123456789` |
| `<ORG>` | The GitHub organization that owns the repos | `acme` |
| `<TOKEN_FILE>` | Absolute path of the owner-written 0600 token file | `/Users/me/.config/gh-swarm-bot/token` |
| `<WRAPPER_NAME>` | What you call the wrapper on `PATH` | `bot-gh` |

The full setup (creating the account, team, token, branch protection) is in
the repo's `docs/setting-up-a-worker-identity.md`.

## The identity

| What | Value |
|---|---|
| GitHub user | `<BOT_USER>` (id `<BOT_ID>`) |
| Org access | A `<ORG>` team (for example `workers`) with Write on the swarm's repos |
| Commit author | `<BOT_USER> <<BOT_ID>+<BOT_USER>@users.noreply.github.com>` |
| Token file | `<TOKEN_FILE>`, mode 0600, written by the owner from a password manager. Agents never read it directly |
| Wrapper | `<WRAPPER_NAME>` (from `scripts/worker-gh`): exports `GH_TOKEN` from the token file into the `gh` it execs, nothing else |
| Token | Fine-grained PAT with an expiry, resource owner `<ORG>` |
| Token permissions | Contents RW, Pull requests RW, Metadata R on the swarm's repos. **No Workflows permission**, unless you deliberately want workers to change CI |

## Rules for the token (read these first)

The token can write to every repo the bot can reach. Treat it like a
credential:

- **Never print, echo, `cat` or log it.** Never run `gh auth status -t` /
  `--show-token` or `gh auth token`. Never put it in argv, an env var you set
  yourself, a file, a commit, a PR body, the wiki or a chat reply.
- **Never read the token file, the OS keychain or the password manager
  yourself.** Run everything the bot does through `<WRAPPER_NAME>`, which
  reads the file inside its own process.
- **Never `gh auth login` as the bot, with or without `GH_CONFIG_DIR`.** gh
  on macOS keeps **one shared active-token slot per host** in the keyring
  (service `gh:github.com`). `GH_CONFIG_DIR` does not isolate it, so a bot
  login overwrites the owner's token: the owner's default `gh` then acts as
  the bot, and once the owner logs back in, the "bot" config acts as the
  owner. `GH_TOKEN` takes precedence over stored credentials and never
  touches that slot, which is why the wrapper uses it.
- **Only the owner writes the token file.** If it is missing or expired, stop
  and ask the owner. Do not fix auth by falling back to the owner's SSH key or
  default `gh` login. That would quietly publish work as the owner.
- **HTTPS only, never SSH.** SSH would use the owner's key.

Every diagnostic below is read-only and shows at most a login name and an
expiry date.

## 1. Set the commit author (once per worktree)

Never use `--global`: the global config belongs to the owner. Watch out for
linked worktrees (herdr workers usually run in one): there,
`git config --local` writes to the **shared** `.git/config`, so every
worktree of that repo starts committing as the bot. Check which kind you are
in:

```sh
git rev-parse --git-dir --git-common-dir   # different paths = linked worktree
git config --get extensions.worktreeConfig # true = per-worktree config is on
```

- **Own clone, or `extensions.worktreeConfig` is already `true`.** Set it once:

  ```sh
  git config --worktree user.name  "<BOT_USER>"
  git config --worktree user.email "<BOT_ID>+<BOT_USER>@users.noreply.github.com"
  ```

  (`--worktree` is the same as `--local` when the extension is off, so use
  it only after you have checked.)
- **Linked worktree without the extension.** Do not change the shared config
  or turn the extension on yourself; both affect every other worktree. Pass
  the identity on each commit instead:

  ```sh
  git -c user.name=<BOT_USER> -c user.email=<BOT_ID>+<BOT_USER>@users.noreply.github.com commit ...
  ```

Check it before committing:

```sh
git config --show-scope --show-origin --get-all user.email
```

## 2. Commit

```sh
GIT_CONFIG_GLOBAL=/dev/null git commit -F commit-msg.txt
# linked worktree without worktreeConfig: add the two -c flags from step 1
git log -1 --format='%an <%ae> | %cn <%ce>'   # both must be <BOT_USER>
```

`GIT_CONFIG_GLOBAL=/dev/null` keeps the owner's global settings out of the
commit, such as an SSH commit-signing setup that would raise a password
manager prompt. If the PR already has a commit and your team wants one commit
per PR, fold changes in with `git commit --amend`.

## 3. Push over HTTPS

Put the wrapper on `PATH` for the shell you run git from (or use its absolute
path everywhere `<WRAPPER_NAME>` appears):

```sh
export PATH="<dir-containing-the-wrapper>:$PATH"
<WRAPPER_NAME> api user -q .login              # expect: <BOT_USER>
```

```sh
GIT_TERMINAL_PROMPT=0 \
GIT_CONFIG_GLOBAL=/dev/null \
git -c credential.helper= -c credential.helper='!<WRAPPER_NAME> auth git-credential' \
  push -u https://github.com/<ORG>/<repo>.git <branch>
```

Why each piece is there:

| Piece | Why |
|---|---|
| `GIT_TERMINAL_PROMPT=0` | A missing credential fails fast instead of hanging on a username prompt |
| `GIT_CONFIG_GLOBAL=/dev/null` | Drops the owner's global config, notably a `url.git@github.com:<ORG>/.insteadOf https://github.com/<ORG>/` rule, which would silently rewrite the HTTPS URL to SSH and push with the owner's key |
| `-c credential.helper=` | The empty value **resets** the helper list, dropping helpers from lower-priority config such as Apple git's system `osxkeychain`, which could hand git the owner's stored credential |
| `-c credential.helper='!<WRAPPER_NAME> auth git-credential'` | Git asks `gh` (with the bot's `GH_TOKEN`) for the credential, so the token goes through the helper protocol on stdin/stdout and never appears in argv or the keyring |
| The full `https://` URL | Does not depend on how `origin` is configured (it is often an SSH URL) |

For a rewrite of an already-pushed branch (amend, rebase), lease against the
SHA you last pushed so you never clobber someone else's push:

```sh
GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null \
git -c credential.helper= -c credential.helper='!<WRAPPER_NAME> auth git-credential' \
  push --force-with-lease=<branch>:<last-pushed-sha> \
  https://github.com/<ORG>/<repo>.git <branch>
```

Fetch the same way when you need the latest base:

```sh
GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null \
git -c credential.helper= -c credential.helper='!<WRAPPER_NAME> auth git-credential' \
  fetch https://github.com/<ORG>/<repo>.git main:refs/remotes/origin/main
```

## 4. Open the PR as a draft

```sh
<WRAPPER_NAME> pr create --draft \
  --repo <ORG>/<repo> --base main --head <branch> \
  --title "feat(scope): summary" \
  --body-file pr-body.md
<WRAPPER_NAME> pr view <number> --repo <ORG>/<repo> --json author,isDraft,url
```

`author.login` must be `<BOT_USER>`. Write multi-line bodies to a file inside
the worktree and delete it before you commit anything else. The owner reviews
with a formal Approve; the bot cannot approve its own PR, so do not try.

To request a reviewer explicitly, use the REST endpoint
(`<WRAPPER_NAME> api -X POST repos/<ORG>/<repo>/pulls/<N>/requested_reviewers -f 'reviewers[]=<owner>'`).
`gh pr edit --add-reviewer` looks up org teams, which a narrowly scoped token
usually cannot read.

## 5. Debugging: symptom → cause → fix

Run the read-only checks first. They need `<WRAPPER_NAME>` on `PATH` (step 3).

### Read-only checks

```sh
# Is the token file there with the right mode? (metadata only, not contents)
ls -l "<TOKEN_FILE>"                                          # expect -rw-------

# Who is the owner's gh, and who is the wrapper? (prints logins only)
gh api user -q .login                                         # expect: the owner
<WRAPPER_NAME> api user -q '.login + " " + (.id|tostring)'    # expect: <BOT_USER> <BOT_ID>

# When does the token expire? (response header only; the token is not in it)
<WRAPPER_NAME> api -i user | grep -i '^github-authentication-token-expiration'

# Can the token see the repo? 404 on a private repo = the token cannot reach it
<WRAPPER_NAME> api repos/<ORG>/<repo> --jq .full_name

# Does the *account* have Write (is the team grant there)?
<WRAPPER_NAME> api repos/<ORG>/<repo> --jq .permissions.push  # true = team grant OK

# Does the *token* have write? A dry-run push asks the server for write
# access but sends nothing and changes no ref
GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null \
git -c credential.helper= -c credential.helper='!<WRAPPER_NAME> auth git-credential' \
  push --dry-run https://github.com/<ORG>/<repo>.git HEAD:refs/heads/<branch>

# Would the URL be rewritten to SSH?
git ls-remote --get-url https://github.com/<ORG>/<repo>.git                       # with global config
GIT_CONFIG_GLOBAL=/dev/null git ls-remote --get-url https://github.com/<ORG>/<repo>.git

# Which author will the next commit use?
git config --show-scope --get-all user.email
git log -1 --format='%an <%ae>'
```

Separate the account from the token. `permissions.push` reports what
`<BOT_USER>` *the account* may do (the team grant). The dry-run push reports
what *this token* may do. If the first is `true` and the second is 403, the
token is the problem, not the team.

### Table

| Symptom | Likely cause | Fix |
|---|---|---|
| After a bot login, the owner's default `gh` (or other sessions) act as `<BOT_USER>`, or private repos suddenly 404 for them; or a `GH_CONFIG_DIR=...` "bot" config acts as the owner | gh's **shared keyring slot**: on macOS gh keeps one active token per host (service `gh:github.com`), and `GH_CONFIG_DIR` does not isolate it, so `gh auth login` for the bot overwrote the owner's token (or the reverse) | Owner runs `gh auth logout --hostname github.com --user <BOT_USER>`, logs back in as themselves, writes the token file and uses the wrapper from then on. Never `gh auth login` as the bot again. Check: `gh api user -q .login` vs `<WRAPPER_NAME> api user -q .login` |
| `<WRAPPER_NAME>: ... is missing`, `must be mode 0600` or `is empty` | The owner has not written the token file yet, or wrote it without `umask 077` | Ask the owner to (re)write it. Don't create, chmod or fill it yourself |
| `<WRAPPER_NAME>: edit token_file ...` | The wrapper was installed without replacing the `<TOKEN_FILE>` placeholder | Owner edits the installed wrapper and sets the real path |
| `<WRAPPER_NAME> api user` returns `401 Bad credentials`; the expiry header shows a past date | The fine-grained token expired | Owner rotates the token and rewrites the token file. Agents stop and ask; they don't work around it |
| Push: `403`, `Permission to <ORG>/<repo>.git denied to <BOT_USER>` or `Write access to repository not granted`; `permissions.push` is `true` | The token lacks **Contents: Read and write** for that repo, or the repo is not in the token's repository list | Owner edits the token: add the repo, set Contents RW |
| Private repos 404, public repos are read-only, and **no** repo accepts a dry-run push | The fine-grained token's **org approval is pending**, or the token's resource owner is the bot's personal account instead of `<ORG>` | Owner approves it under the org's Settings → Personal access tokens → Pending requests, or recreates it with `<ORG>` as resource owner |
| Push 403 and `permissions.push` is `false` (or the repo 404s for the account) | The bot is not in the team, or the team lacks Write on that repo | Owner adds the bot to the team / grants the team Write |
| `gh pr create` fails with `Resource not accessible by personal access token` (HTTP 403) after the push succeeded | The token lacks **Pull requests: Read and write** | Owner adds Pull requests RW to the token |
| Push rejected: `refusing to allow a Personal Access Token to create or update workflow .github/workflows/... without workflow scope` | The token has no Workflows permission, by design, so workers cannot change CI | Don't change workflow files from a worker. Split the workflow change out and hand it to the owner |
| `Author identity unknown` / `Please tell me who you are` | No `user.name`/`user.email` reachable once the global config is disabled | Set the author per step 1, then `git commit --amend --reset-author --no-edit` (with the `-c` flags in a linked worktree) |
| Commits or the PR show the owner as author | Author not set (step 1); committed without `GIT_CONFIG_GLOBAL=/dev/null`; or the PR was created with plain `gh` instead of the wrapper | Set the author per step 1, `git commit --amend --reset-author --no-edit`, force-push with lease. A PR opened by the wrong account has to be closed and reopened by the bot |
| Every other worktree of the repo suddenly commits as the bot | Someone ran `git config --local user.*` in a linked worktree, which writes the shared `.git/config` | Remove it from the shared config (`git config --local --unset user.name`, same for `user.email`) and use `--worktree` or per-commit `-c` flags (step 1) |
| Password-manager / SSH-agent prompt (signing, or `git@github.com` auth) during commit, fetch or push | An SSH remote is in use: `origin` is `git@github.com:...`, or a global `url...insteadOf` rewrote the HTTPS URL (check with `git ls-remote --get-url`). For commits, a global SSH signing config | Use the full HTTPS URL with `GIT_CONFIG_GLOBAL=/dev/null` as in step 3; commit with `GIT_CONFIG_GLOBAL=/dev/null`. Cancel the prompt; never approve it for a worker push |
| Push hangs on `Username for 'https://github.com':`, or the helper fails with `<WRAPPER_NAME>: not found` | `GIT_TERMINAL_PROMPT=0` missing and no helper answered; the wrapper is not on `PATH` | Add `GIT_TERMINAL_PROMPT=0` and the two `-c credential.helper` flags; put the wrapper on `PATH` or use its absolute path in the helper |
| Push succeeds but GitHub shows the owner as the pusher | A lower-priority helper (Apple git's system `osxkeychain`) supplied the owner's credential | Add `-c credential.helper=` *before* `-c credential.helper='!<WRAPPER_NAME> auth git-credential'` to reset the helper list |

When you report a failure, give the symptom (exact error line, HTTP status,
which repo), the check outputs above, and your conclusion. Never include the
token, a token prefix, or the contents of any credential file.

## Owner-only: write or rotate the token file

Agents never run this. They tell the owner it is needed. The owner reads the
token from the password manager straight into a 0600 file, so it never
touches argv, shell history or the keyring. With the 1Password CLI:

```sh
mkdir -p "$(dirname "<TOKEN_FILE>")" && chmod 700 "$(dirname "<TOKEN_FILE>")"
( umask 077; op read "op://<vault>/<item>/<field>" > "<TOKEN_FILE>" )
ls -l "<TOKEN_FILE>"                 # -rw-------
<WRAPPER_NAME> api user -q .login    # <BOT_USER>
gh api user -q .login                # still the owner
```

Do **not** use `gh auth login --with-token` for the bot: it stores the token
in the shared keyring slot and replaces the owner's login. To rotate,
overwrite the file the same way.

## Porting

This skill is plain markdown and one POSIX shell script with no
harness-specific tool names. Copy the directory (keep `scripts/worker-gh`
executable, and rename it to `<WRAPPER_NAME>` wherever you install it on
`PATH`):

| Harness | Project skill dir | User skill dir |
|---|---|---|
| Claude Code | `.claude/skills/worker-git-identity/` | `~/.claude/skills/worker-git-identity/` |
| opencode | `.opencode/skills/worker-git-identity/` | `~/.config/opencode/skills/worker-git-identity/` |
| Codex | `.agents/skills/worker-git-identity/` | `~/.agents/skills/worker-git-identity/` |
