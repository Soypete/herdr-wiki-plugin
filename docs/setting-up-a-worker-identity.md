# Setting up a worker identity for your swarm

When you run a herdr swarm, your worker agents commit, push and open pull
requests. By default they do all of that as **you**, because they use your
git config, your SSH key and your `gh` login. This guide sets up a separate
GitHub bot account for the swarm instead, and then walks through the
template skill in [`skills/claude/worker-git-identity/`](../skills/claude/worker-git-identity/SKILL.md)
that teaches workers to use it.

It takes about half an hour, most of it clicking through GitHub settings.

## Why bother

- **You can formally approve the swarm's PRs.** GitHub never lets a PR's
  author approve their own PR. If every worker PR is authored by you, the
  most you can do is leave a comment saying "looks good". With a bot author,
  you review with a real **Approve**, and that approval is recorded against a
  specific commit.
- **Branch protection works.** Once PRs come from someone else, you can
  require a code-owner approval on `main`. Nothing a worker writes merges
  without a human signing off, and a worker can't quietly push to `main`.
- **The audit trail is honest.** Commits, pushes and PRs by agents show up as
  the bot, and work you did by hand shows up as you. When something goes
  wrong, you can tell which is which.
- **The blast radius is smaller.** The bot's token can only write to the repos
  you pick, can't change CI workflows unless you allow it, and expires. Your
  own credentials never leave your machine's normal setup.

Throughout this guide the placeholders match the skill template:

| Placeholder | Meaning |
|---|---|
| `<BOT_USER>` | The bot's GitHub login, for example `acme-swarm-bot` |
| `<BOT_ID>` | The bot's numeric GitHub user id |
| `<ORG>` | Your GitHub organization |
| `<TOKEN_FILE>` | Where the bot's token lives on disk, for example `$HOME/.config/gh-swarm-bot/token` (use the expanded absolute path in the wrapper) |
| `<WRAPPER_NAME>` | The name of the `gh` wrapper on your `PATH`, for example `bot-gh` |

## 1. Create the bot account and add it to the org

1. Sign out of GitHub (or use a private browser window) and sign up for a new
   account, `<BOT_USER>`. GitHub's terms allow one free "machine account" per
   person, as long as a human is responsible for it. Use an email address you
   control, such as a `+bot` alias of your own.
2. Turn on two-factor authentication for the bot. Many orgs require it, and
   the bot can write to your repos.
3. Store the bot's password and 2FA recovery codes in your password manager.
4. Note its numeric id, which you need for the commit email:

   ```sh
   gh api users/<BOT_USER> -q .id
   ```

5. As an org owner, invite `<BOT_USER>` to `<ORG>` as a **member** (not an
   owner), then accept the invitation while signed in as the bot.

## 2. Create a team with Write on the swarm's repos

Grant access through a team rather than per repo, so adding a repo later is
one click.

1. In `<ORG>` → **Teams** → **New team**, create a team such as `workers` and
   add `<BOT_USER>`.
2. For each repo the swarm works in: repo **Settings** → **Collaborators and
   teams** → **Add teams** → `workers` → role **Write**.

Write is enough to push branches and open PRs. Don't give the team Maintain or
Admin: those can change branch protection, which defeats the point.

## 3. Create a fine-grained personal access token

Signed in **as the bot**, go to **Settings** → **Developer settings** →
**Personal access tokens** → **Fine-grained tokens** → **Generate new token**:

| Field | Value |
|---|---|
| Token name | something like `herdr swarm` |
| Resource owner | **`<ORG>`**, not the bot's personal account. A token owned by the personal account can't see private org repos |
| Expiration | 90 days is a reasonable default. Put a reminder in your calendar |
| Repository access | **Only select repositories**: the repos the team has Write on |
| Contents | **Read and write**: push branches |
| Pull requests | **Read and write**: open, update and mark PRs ready |
| Metadata | **Read-only**: GitHub selects this automatically |
| Workflows | Leave it **off** unless you want workers to edit `.github/workflows/`. Without it, a push that touches a workflow file is rejected, which keeps CI changes in human hands |

Everything else stays at **No access**. If you later want workers to read CI
results, add **Checks**, **Commit statuses** and **Actions** as read-only.

**Org approval.** If `<ORG>` requires approval for fine-grained tokens
(**Org Settings** → **Personal access tokens** → **Settings**), the new token
sits in **Pending requests** and can only read public repos until an org
owner approves it. Approve it there. A token that 404s on every private repo
is almost always waiting for this.

## 4. Store the token and write the token file

GitHub shows the token once. Paste it straight into your password manager as
a new item. Don't paste it into a terminal, a chat or a notes file.

Then write it to a file only your user can read. The point is that the token
never appears in your shell history, in a process list or on screen. With
the 1Password CLI:

```sh
mkdir -p "$HOME/.config/gh-swarm-bot" && chmod 700 "$HOME/.config/gh-swarm-bot"
( umask 077; op read "op://<vault>/<item>/<field>" > "$HOME/.config/gh-swarm-bot/token" )
ls -l "$HOME/.config/gh-swarm-bot/token"    # -rw-------
```

Without a password manager CLI, read it from the terminal with echo turned
off and paste it at the prompt (`read` and `printf` are shell builtins, so the
token never shows up in a process list):

```sh
( umask 077
  stty -echo; printf 'token: '; IFS= read -r t; stty echo; echo
  printf '%s\n' "$t" > "$HOME/.config/gh-swarm-bot/token" )
```

**Don't run `gh auth login` with the bot's token**, even with a separate
`GH_CONFIG_DIR`. On macOS, `gh` stores tokens in the system keyring with one
active slot per host (`gh:github.com`), and `GH_CONFIG_DIR` doesn't separate
it. Logging the bot in replaces your own login: your `gh` starts acting as
the bot in every terminal. The wrapper in the next step avoids the keyring
completely. If it already happened, see [Recovering from the keyring
trap](#recovering-from-the-keyring-trap).

## 5. Install the wrapper and the skill

The wrapper is a small POSIX shell script that reads the token file and passes
it to `gh` as `GH_TOKEN`, only for that one process. `GH_TOKEN` takes
precedence over anything stored, so your own `gh` login is untouched. It
refuses to run if the token file is missing, empty or readable by anyone but
you, and it never prints the token.

```sh
mkdir -p "$HOME/.local/bin"
cp skills/claude/worker-git-identity/scripts/worker-gh "$HOME/.local/bin/<WRAPPER_NAME>"
chmod 755 "$HOME/.local/bin/<WRAPPER_NAME>"
# then edit the token_file= line in it to the absolute path of your token file
```

Next, install the skill for your workers' harnesses. Copy the skill directory
without `evals/` and replace the placeholders in `SKILL.md` with your values,
so workers see real names and commands:

| Harness | Where |
|---|---|
| Claude Code | `~/.claude/skills/worker-git-identity/` (or `.claude/skills/` in a project) |
| opencode | `~/.config/opencode/skills/worker-git-identity/` (or `.opencode/skills/` in a project; allow it in `opencode.json`) |
| Codex | Comes with the `herdr-wiki` plugin; see [`skills/README.md`](../skills/README.md#codex). Edit the installed copy |

## 6. Set the commit author per worktree

Commits need the bot as author, set for each worktree and **never with
`--global`** (your global config is yours). Use the bot's noreply address so
GitHub links commits to the account:

```sh
git config --worktree user.name  "<BOT_USER>"
git config --worktree user.email "<BOT_ID>+<BOT_USER>@users.noreply.github.com"
```

There's a catch with herdr worktrees. In a **linked** worktree,
`git config --local` writes to the repo's shared `.git/config`, so every
worktree of that repo, including your own checkout, starts committing as the
bot. `--worktree` keeps the setting per worktree, but only when the repo has
`extensions.worktreeConfig` turned on. To turn it on once per repo (do this
yourself, not from a worker):

```sh
git config extensions.worktreeConfig true
```

Without it, workers pass the identity per commit with
`git -c user.name=... -c user.email=... commit`. The skill explains how they
tell the difference.

## 7. Verify with read-only checks

None of these change anything or print the token:

```sh
gh api user -q .login                                         # you
<WRAPPER_NAME> api user -q '.login + " " + (.id|tostring)'    # <BOT_USER> <BOT_ID>
<WRAPPER_NAME> api -i user | grep -i '^github-authentication-token-expiration'
<WRAPPER_NAME> api repos/<ORG>/<repo> --jq .permissions.push  # true

# Asks GitHub for write access but sends nothing and changes no ref
GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null \
git -c credential.helper= -c credential.helper='!<WRAPPER_NAME> auth git-credential' \
  push --dry-run https://github.com/<ORG>/<repo>.git HEAD:refs/heads/identity-check
```

That last command is also the shape of every real worker push. Each part
closes a hole that would otherwise push as you:

- `GIT_CONFIG_GLOBAL=/dev/null` ignores your global git config, including any
  `url.git@github.com:.insteadOf https://github.com/` rule that would silently
  turn the HTTPS URL into SSH and use your SSH key.
- `-c credential.helper=` clears the helper list first. Apple's git ships a
  system-level `osxkeychain` helper that would otherwise offer git your own
  stored GitHub credential.
- `-c credential.helper='!<WRAPPER_NAME> auth git-credential'` makes git ask
  the wrapper, which answers with the bot's token over stdin.
- The full `https://` URL doesn't depend on `origin`, which is often SSH.
- `GIT_TERMINAL_PROMPT=0` makes a missing credential fail fast instead of
  hanging on a username prompt.

If any check fails, the skill's debugging table maps the exact error to its
cause.

## 8. Add CODEOWNERS and branch protection

Now make the review count. In each repo, add `.github/CODEOWNERS` naming the
humans who review swarm work:

```
* @your-github-user @a-teammate
```

Don't list the bot. Then protect `main` (**Settings** → **Branches** → add a
rule, or **Rules** → **Rulesets** → new branch ruleset targeting the default
branch):

- **Require a pull request before merging**
  - Required approvals: **1**
  - **Require review from Code Owners**
  - **Dismiss stale pull request approvals when new commits are pushed**, so
    an approval always covers the code that merges
- **Require status checks to pass**, if the repo has CI
- **Block force pushes** and **Restrict deletions**
- Don't add the bot or the `workers` team to any bypass list

Add the CODEOWNERS file and the rules yourself, not from a worker. They decide
who can merge, so a human should make that change.

From now on: a worker opens a draft PR as the bot, marks it ready when it's
done (which requests the code owners), and you approve or request changes.

## Rotating the token

Fine-grained tokens expire. A week or so before the date shown by the expiry
check in step 7:

1. Signed in as the bot, open the token and **Regenerate** it (keeps the same
   permissions), or create a new one with the same settings.
2. If the org requires approval, approve the new token.
3. Update the password manager item.
4. Overwrite the token file exactly as in step 4. Nothing else changes: the
   wrapper reads the file on every call.
5. Run the checks in step 7, then delete the old token if you created a new
   one.

If you think the token leaked, revoke it first (as the bot, or as an org
owner under **Org Settings** → **Personal access tokens** → **Active
tokens**), then create a new one.

## Recovering from the keyring trap

Symptoms: right after someone ran `gh auth login` as the bot, your own
`gh api user -q .login` prints the bot, your private repos 404 in other
terminals, or a "bot" `GH_CONFIG_DIR` acts as you.

1. Log the bot out of the shared slot and log yourself back in:

   ```sh
   gh auth logout --hostname github.com --user <BOT_USER>
   gh auth login                      # as yourself
   gh api user -q .login              # you again
   ```

2. Delete any separate `gh` config directory created for the bot's login
   (not the token file directory if they're the same).
3. Write the token file (step 4) and use the wrapper from then on.
4. Confirm the two identities are separate:

   ```sh
   gh api user -q .login              # you
   <WRAPPER_NAME> api user -q .login  # <BOT_USER>
   ```

If the token was ever pasted somewhere visible while fixing this, rotate it.
