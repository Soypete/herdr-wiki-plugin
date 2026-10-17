#!/usr/bin/env bash
# Cancel CI runs whose PR is already merged or closed.
#
# An eval run for an already-merged branch held every self-hosted runner for
# ~5h while other PR gates sat queued (issue #20, observation 4). This is the
# orchestrator-side cleanup: cancel runs whose head branch is no longer an
# open PR.
#
# Usage: cancel-stale-runs.sh [--repo OWNER/NAME ...] [--dry-run]
set -euo pipefail

repos=()
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repos+=("$2"); shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ${#repos[@]} -eq 0 ]]; then
  if r=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null); then
    repos=("$r")
  else
    echo "no repo given and cwd is not a repo; pass --repo OWNER/NAME" >&2
    exit 2
  fi
fi

cancelled=0
for repo in "${repos[@]}"; do
  declare -A open_heads=()
  while read -r head; do
    [[ -n "$head" ]] && open_heads["$head"]=1
  done < <(gh pr list --repo "$repo" --state open --json headRefName \
             --jq '.[].headRefName' 2>/dev/null || true)

  while IFS=$'\t' read -r run_id status event head; do
    [[ -z "${run_id:-}" || -z "${head:-}" ]] && continue
    if [[ -z "${open_heads[$head]:-}" ]]; then
      if [[ $dry_run -eq 1 ]]; then
        echo "would cancel run $run_id ($repo, branch $head, status $status)"
      else
        gh run cancel "$run_id" --repo "$repo" >/dev/null 2>&1 || true
        echo "cancelled stale run $run_id ($repo, branch $head)"
      fi
      cancelled=$((cancelled + 1))
    fi
  done < <(gh run list --repo "$repo" --limit 50 --json databaseId,status,event,headBranch \
             --jq '.[] | select(.status == "in_progress" or .status == "queued") |
                   [.databaseId, .status, .event, .headBranch] | @tsv' 2>/dev/null || true)
done
echo "done: $cancelled stale run(s) ${dry_run:+would be }handled"
