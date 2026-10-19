#!/usr/bin/env bash
# Ensure every non-draft, unapproved PR requests review from the owner.
#
# `gh pr edit --add-reviewer` fails with fine-grained bot tokens
# ("Resource not accessible by personal access token (organization.teams)"),
# so reviewer requests went missing and the owner never saw the PRs
# (issue #20, observation 5). This script uses the REST endpoint
# POST /repos/{owner}/{repo}/pulls/{number}/requested_reviewers instead.
#
# Usage: request-reviewers.sh [--owner OWNER/NAME ...] --reviewer <user>
#        [--repo OWNER/NAME ...] [--dry-run]
set -euo pipefail

reviewer=""
declare -a repos=()
owner_repo=""
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repos+=("$2"); shift 2 ;;
    --owner) owner_repo="$2"; shift 2 ;;
    --reviewer) reviewer="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$reviewer" ]]; then
  echo "usage: request-reviewers.sh --reviewer <github-user> [--repo OWNER/NAME ...]" >&2
  exit 2
fi

if [[ ${#repos[@]} -eq 0 ]]; then
  if r=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null); then
    repos=("$r")
  else
    echo "no repo given and cwd is not a repo; pass --repo OWNER/NAME" >&2
    exit 2
  fi
fi

requested=0
for repo in "${repos[@]}"; do
  org="${repo%%/*}"
  api="api.github.com"
  # non-draft, unapproved, open PRs
  while IFS=$'\t' read -r number draft_state; do
    [[ -z "${number:-}" ]] && continue
    [[ "$draft_state" == "true" ]] && continue
    app=1
    if reviews=$(gh api "repos/$repo/pulls/$number/reviews" --jq '.[].state' 2>/dev/null); then
      if grep -q "APPROVED" <<<"$reviews"; then app=0; fi
    fi
    if [[ $app -eq 0 ]]; then continue; fi
    already=$(gh api "repos/$repo/pulls/$number/requested_reviewers" \
                --jq '.users[].login' 2>/dev/null || true)
    if grep -qx "$reviewer" <<<"$already"; then continue; fi
    if [[ $dry_run -eq 1 ]]; then
      echo "would request $reviewer on $repo#$number"
    else
      if gh api -X POST "repos/$repo/pulls/$number/requested_reviewers" \
           -f "reviewers[]=$reviewer" >/dev/null 2>&1; then
        who=$(gh api "repos/$repo/pulls/$number/requested_reviewers" \
                --jq '.users[].login' 2>/dev/null | tr '\n' ' ' || true)
        if grep -qx "$reviewer" <<<"$who"; then
          echo "requested review on $repo#$number for $reviewer"
          requested=$((requested + 1))
        else
          echo "WARN: request call succeeded but $repo#$number does not list $reviewer" >&2
        fi
      else
        echo "WARN: could not request reviewer on $repo#$number (fine-grained tokens cannot resolve teams; verify in the UI)" >&2
      fi
    fi
  done < <(gh pr list --repo "$repo" --state open --json number,isDraft \
             --jq '.[] | [.number, .isDraft] | @tsv' 2>/dev/null || true)
done
echo "done: $requested reviewer request(s)"
