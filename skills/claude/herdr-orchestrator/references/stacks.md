# Stacks and parallel work

Stacks are sequential by nature: each PR builds on the one below. Parallelism comes from running **several independent stacks at once**, not from parallel workers inside one stack.

## Mapping tasks to stacks

- **Independent tasks** → separate stacks (or single PRs), separate worktrees, run in parallel.
- **Dependent tasks** → one stack, ordered bottom to top. The upstream task goes first.
- **Downstream start** → a worker on layer N+1 may start once layer N's interface is settled (its `decision`/contract is in the wiki), even before layer N's PR is open, as long as it codes against the agreed contract. It opens its PR only after layer N's PR exists.
- **Cross-repo** → stacks don't span repos. Link the related PRs in each PR description and in the `release` capture.

Keep stacks short (2–4 layers). A tall stack multiplies restack pain and review latency.

## gh stack commands workers use

(Public preview; stacks must be enabled on the repo. Check `gh stack --help` for current flags.)

- `gh stack init` — bottom layer starts a new stack.
- `gh stack add <branch>` — a new layer on top of the current stack.
- `gh stack submit` — push all branches and create/update the PRs and stack.
- `gh stack sync` / `gh stack rebase` — restack after a lower layer changes.
- `gh stack view` — orchestrator uses this to verify structure.

Workers never run `gh stack merge`. Merging belongs to the user.

## Worktrees for stacked layers

Each layer's worker needs its own worktree checked out at its own branch. Create the lower layer's branch first; the upper worker's worktree branches from it. Two workers must never share a checkout.

## Who restacks

The worker that owns a branch restacks it. When a lower layer changes (review feedback, a fix after a failed e2e):

1. Lower worker pushes its change (`gh stack submit`).
2. Orchestrator prompts each worker above it, bottom to top: *"Layer below changed. Run `gh stack sync`, fix conflicts in your files only, rerun `<test command>`, resubmit."*
3. If the owning worker is gone, start a fresh worker with a restack-only brief. The orchestrator still doesn't resolve conflicts itself.

## One owner per stack

A stack needs one owner that holds its local tracking. When several workers each build one layer in their own worktree, one of them (or a dedicated restack worker) must own the stack from `gh stack init` through `add` and `submit`. `gh stack link` after the fact only registers the stack on GitHub. It gives no local tracking, so `gh stack rebase`/`sync` won't work and every restack becomes manual. Don't write "merge X before Y" notes in PR bodies in place of a stack: if the order matters, stack them.

## Ordered resources: migrations and other numbered sequences

Stacks order **dependent** PRs. They don't protect **independent** PRs that each claim a slot in a shared ordered sequence, such as goose/SQL migration numbers. Two unrelated PRs can each add a migration and both merge green. If the lower-numbered one merges after the higher one has already applied, goose (without allow-missing) refuses to start: `found 1 missing migrations before current version N`. The deploy crash-loops.

Prevent it this way, not by stacking unrelated work:

1. **A CI guard** in the repo: fail a PR whose new migration number is below the highest migration number on the base branch. Make it a file-name check with no DB.
2. **Workers check the current max on `origin/main`** when they open the PR and again right before merge, and renumber an unapplied migration if needed. Renaming is safe only if the migration has never been applied anywhere.
3. **Rebase before merge**, so the guard runs against current main.
4. Wiki number claims are coordination hints only; the CI guard enforces the order.

### The orchestrator enforces merge order

The CI guard only catches the problem after a merge has already made an open PR stale. The orchestrator must prevent it up front, using the wiki:

1. **Track every open migration.** When a worker's PR adds a migration, record `repo, PR, migration number` in the wiki (`wiki capture --type decision --title "Migration merge order: <repo>"`, and supersede it whenever the list changes). Workers still capture their own number claims; this record is the orchestrator's ordered view.
2. **Give the user an explicit merge order.** Whenever you list PRs for review in a repo with more than one open migration, state the order by migration number ("merge #103 (065) before #112 (066) before #111 (067)"). Never list migration PRs as "merge anytime".
3. **Never let a lower number wait behind a higher one.** If a PR is blocked (for example, it pairs with a PR in another repo), renumber its migration above every other open migration in that repo *before* the user merges anything else. Don't leave it to be discovered after the fact.
4. **On every merge, re-check.** When the PR watcher reports a merge in a repo, list the open PRs in that repo that add migrations. Any with a number at or below the merged one must be renumbered by their owner right away (rebase, rename, one commit, force-push). Tell the user not to merge it until it's pushed.

If a migration-order failure reaches a deploy, renumber the unapplied migration above the current DB version in a small urgent PR. The old pods keep serving during a failed rolling update, so there's time.

## Fallback without gh stack

`gh pr create --base <parent-branch>` for each layer, bottom up. Restacking becomes a manual `git rebase <parent>` by the owning worker. Note the fallback once in the report.
