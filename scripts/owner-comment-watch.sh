#!/usr/bin/env bash
# owner-comment-watch.sh - print one line per NEW comment or review by the owner
# that does not carry the agent marker (default <!-- orch-session -->).
#
# Agents posting as the owner account end every comment with the marker, so
# anything without it was typed by the owner (often from mobile) and needs an
# answer. Reads the owner's events feed; private events are included only
# when gh is authenticated as the owner. Events older than the first run are
# ignored (the start time is stored next to the seen-list).
#
# It only prints. It never replies or changes anything.
#
# Environment (all optional):
#   OWNER_LOGIN   login whose comments to watch     (default: the gh-authenticated user)
#   WATCH_ORGS    space-separated users/orgs; only events in their repos are
#                 printed (default: unset = every repo)
#   MARKER        text that marks an agent comment  (default: orch-session)
#   STATE_DIR     where the seen-list and start time live
#                 (default: ${TMPDIR:-/tmp}/owner-comment-watch)
#   INTERVAL      seconds between polls             (default: 150)
#   CYCLES        polls before exiting; 0 = forever (default: 12)
#
# Requires: gh (authenticated), python3, bash.
set -u

OWNER_LOGIN="${OWNER_LOGIN:-$(gh api user --jq .login 2>/dev/null)}"
if [ -z "$OWNER_LOGIN" ]; then
  echo "owner-comment-watch: set OWNER_LOGIN or authenticate gh" >&2
  exit 2
fi
WATCH_ORGS="${WATCH_ORGS:-}"
MARKER="${MARKER:-orch-session}"
STATE_DIR="${STATE_DIR:-${TMPDIR:-/tmp}/owner-comment-watch}"
INTERVAL="${INTERVAL:-150}"
CYCLES="${CYCLES:-12}"

mkdir -p "$STATE_DIR"
SEEN="$STATE_DIR/seen"
START_FILE="$STATE_DIR/start"
touch "$SEEN"
[ -s "$START_FILE" ] || date -u +%Y-%m-%dT%H:%M:%SZ >"$START_FILE"
START=$(cat "$START_FILE")

cycle=0
while :; do
  cycle=$((cycle + 1))
  gh api "users/$OWNER_LOGIN/events?per_page=40" 2>/dev/null </dev/null |
    python3 -c '
import json, sys
start, marker, orgs = sys.argv[1], sys.argv[2], sys.argv[3].split()
try:
    events = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for e in events:
    if e.get("created_at", "") < start:
        continue
    t, p = e.get("type"), e.get("payload", {})
    repo = e.get("repo", {}).get("name", "")
    if orgs and repo.split("/")[0] not in orgs:
        continue
    if p.get("action") != "created":
        continue
    if t == "IssueCommentEvent":
        c = p["comment"]; n = p["issue"]["number"]
        body = c.get("body") or ""; key = "c%s" % c["id"]
    elif t == "PullRequestReviewEvent":
        r = p["review"]; n = p["pull_request"]["number"]
        body = "[%s] %s" % (r.get("state"), r.get("body") or ""); key = "r%s" % r["id"]
    elif t == "PullRequestReviewCommentEvent":
        c = p["comment"]; n = p["pull_request"]["number"]
        body = c.get("body") or ""; key = "rc%s" % c["id"]
    else:
        continue
    if marker in body:
        continue
    print(key, repo, n, " ".join(body.split())[:220])
' "$START" "$MARKER" "$WATCH_ORGS" |
    while read -r key repo n rest; do
      grep -qxF "$key" "$SEEN" && continue
      echo "$key" >>"$SEEN"
      echo "OWNER-COMMENT $repo#$n: $rest"
    done
  if [ "$CYCLES" -gt 0 ] && [ "$cycle" -ge "$CYCLES" ]; then break; fi
  sleep "$INTERVAL"
done
echo "owner-comment-watch: cycle limit reached ($CYCLES), re-arm"
