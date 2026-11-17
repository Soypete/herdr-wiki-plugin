#!/usr/bin/env bash
# approval-watch.sh - print one line per PR that is ready for an owner-approved merge.
#
# A PR is announced when ALL of these hold:
#   - state OPEN and not a draft (state is checked first: GitHub reports
#     mergeStateStatus UNKNOWN for PRs that are already merged)
#   - base branch == the repo's default branch (a stacked PR is never merged
#     into its parent branch; the parent lands first, then the child is
#     retargeted and re-approved)
#   - reviewDecision APPROVED and mergeStateStatus CLEAN
#   - $OWNER_LOGIN has an APPROVED review on the exact current head sha
#   - every check passes (`gh pr checks` exits 0; a PR with no checks is not announced)
#   - not in $SKIP_PRS, author not excluded, author allowed by $ONLY_AUTHORS
#
# It only prints. It never merges, comments or changes anything.
# Each repo#N@head is announced once (state file), so a new push re-announces
# only after a new approval on the new head.
#
# Environment (all optional):
#   OWNER_LOGIN      login whose approval counts       (default: the gh-authenticated user)
#   WATCH_ORGS       space-separated users/orgs to search (default: $OWNER_LOGIN)
#   SKIP_PRS         space-separated owner/repo#N held PRs (default: none)
#   EXCLUDE_AUTHORS  space-separated author globs to skip (default: "*dependabot*")
#   ONLY_AUTHORS     space-separated author logins; if set, only these are announced
#                    (default: unset = any author not excluded)
#   STATE_FILE       seen-list path                    (default: ${TMPDIR:-/tmp}/approval-watch.seen)
#   INTERVAL         seconds between polls             (default: 180)
#   CYCLES           polls before exiting; 0 = forever (default: 9)
#   SEARCH_LIMIT     max PRs per search                (default: 60)
#
# Requires: gh (authenticated), bash.
set -u

OWNER_LOGIN="${OWNER_LOGIN:-$(gh api user --jq .login 2>/dev/null)}"
if [ -z "$OWNER_LOGIN" ]; then
  echo "approval-watch: set OWNER_LOGIN or authenticate gh" >&2
  exit 2
fi
WATCH_ORGS="${WATCH_ORGS:-$OWNER_LOGIN}"
SKIP_PRS="${SKIP_PRS:-}"
EXCLUDE_AUTHORS="${EXCLUDE_AUTHORS-*dependabot*}"
ONLY_AUTHORS="${ONLY_AUTHORS:-}"
STATE_FILE="${STATE_FILE:-${TMPDIR:-/tmp}/approval-watch.seen}"
INTERVAL="${INTERVAL:-180}"
CYCLES="${CYCLES:-9}"
SEARCH_LIMIT="${SEARCH_LIMIT:-60}"

touch "$STATE_FILE"

owner_args=()
for org in $WATCH_ORGS; do owner_args+=(--owner "$org"); done

author_excluded() {
  local a="$1" pat
  set -f
  for pat in $EXCLUDE_AUTHORS; do
    # shellcheck disable=SC2254
    case "$a" in $pat) set +f; return 0 ;; esac
  done
  set +f
  if [ -n "$ONLY_AUTHORS" ]; then
    case " $ONLY_AUTHORS " in *" $a "*) return 1 ;; esac
    return 0
  fi
  return 1
}

check_pr() {
  local repo="$1" n="$2" author="$3" info state draft base head merge decision default key
  case " $SKIP_PRS " in *" $repo#$n "*) return ;; esac
  author_excluded "$author" && return

  info=$(gh pr view "$n" -R "$repo" \
    --json state,isDraft,baseRefName,headRefOid,mergeStateStatus,reviewDecision \
    --jq '[.state, .isDraft, .baseRefName, .headRefOid, .mergeStateStatus, (.reviewDecision // "")] | @tsv' \
    2>/dev/null </dev/null) || return
  IFS=$'\t' read -r state draft base head merge decision <<<"$info"

  [ "$state" = "OPEN" ] || return          # check state first: merged PRs report UNKNOWN
  [ "$draft" = "false" ] || return
  default=$(gh repo view "$repo" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null </dev/null) || return
  [ -n "$default" ] && [ "$base" = "$default" ] || return
  [ "$merge" = "CLEAN" ] && [ "$decision" = "APPROVED" ] || return

  gh api "repos/$repo/pulls/$n/reviews" --paginate \
    --jq ".[] | select(.state == \"APPROVED\" and .user.login == \"$OWNER_LOGIN\") | .commit_id" \
    2>/dev/null </dev/null | grep -qx "$head" || return
  gh pr checks "$n" -R "$repo" >/dev/null 2>&1 </dev/null || return

  key="$repo#$n@$head"
  grep -qxF "$key" "$STATE_FILE" && return
  echo "$key" >>"$STATE_FILE"
  echo "READY-TO-MERGE $repo#$n author=$author head=${head:0:8}"
}

cycle=0
while :; do
  cycle=$((cycle + 1))
  gh search prs "${owner_args[@]}" --state open --review approved --draft=false \
    --limit "$SEARCH_LIMIT" --json repository,number,author \
    --jq '.[] | [.repository.nameWithOwner, (.number | tostring), .author.login] | @tsv' \
    2>/dev/null </dev/null |
    while IFS=$'\t' read -r repo n author; do
      [ -n "$repo" ] && check_pr "$repo" "$n" "$author"
    done
  if [ "$CYCLES" -gt 0 ] && [ "$cycle" -ge "$CYCLES" ]; then break; fi
  sleep "$INTERVAL"
done
echo "approval-watch: cycle limit reached ($CYCLES), re-arm"
