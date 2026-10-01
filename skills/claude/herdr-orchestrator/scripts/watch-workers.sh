#!/usr/bin/env bash
# watch-workers.sh — background watcher for herdr worker agents.
#
# Polls each named worker on an interval and appends one line per meaningful
# event to a log the orchestrator tails. It never sends input to workers;
# deciding whether and how to nudge is the orchestrator's job.
#
# Events:
#   STATE    <name> <state>   first observation of a worker
#   SETTLED  <name> <state>   worker went idle/done (finished or stopped early)
#   BLOCKED  <name>           worker is showing an approval/question UI
#   WORKING  <name>           worker resumed working
#   STALL    <name> <cycles>  working, but recent output unchanged for N cycles
#   GONE     <name>           no live agent by that name (exited or released)
#
# Usage:
#   watch-workers.sh [--log FILE] [--interval SECS] [--stall CYCLES] name [name...]
#
# Portable to macOS bash 3.2 (no associative arrays; state kept in files).

set -u

LOG=/tmp/herdr-watch.log
INTERVAL=60
STALL=3
NAMES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --log) LOG="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --stall) STALL="$2"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) NAMES+=("$1"); shift ;;
  esac
done

if [ "${HERDR_ENV:-}" != 1 ]; then
  echo "watch-workers: not inside a herdr pane (HERDR_ENV != 1)" >&2
  exit 1
fi
if [ ${#NAMES[@]} -eq 0 ]; then
  echo "watch-workers: give at least one worker name" >&2
  exit 2
fi

STATE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/herdr-watch.XXXXXX")
trap 'rm -rf "$STATE_DIR"' EXIT

emit() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >> "$LOG"; }

# Extract the lifecycle state from `herdr agent get` JSON without depending on
# an exact field path: take the first known state word that appears as a JSON
# string value. Verify against `herdr agent get <name>` output if herdr changes.
agent_state() {
  herdr agent get "$1" 2>/dev/null \
    | grep -oE '"(idle|done|working|blocked|unknown)"' \
    | head -n 1 | tr -d '"'
}

output_sig() {
  herdr agent read "$1" --source recent-unwrapped --lines 40 2>/dev/null | cksum | cut -d' ' -f1
}

emit "WATCH start names=${NAMES[*]} interval=${INTERVAL}s stall=${STALL}"

while :; do
  live=0
  for n in "${NAMES[@]}"; do
    f="$STATE_DIR/$n"
    prev=$(cat "$f.state" 2>/dev/null || true)

    if ! herdr agent get "$n" >/dev/null 2>&1; then
      if [ "$prev" != gone ]; then emit "GONE $n"; echo gone > "$f.state"; fi
      continue
    fi
    live=$((live + 1))

    cur=$(agent_state "$n")
    [ -z "$cur" ] && cur=unknown

    if [ "$cur" != "$prev" ]; then
      case "$cur" in
        idle|done) [ -z "$prev" ] && emit "STATE $n $cur" || emit "SETTLED $n $cur" ;;
        blocked)   emit "BLOCKED $n" ;;
        working)   [ -z "$prev" ] && emit "STATE $n working" || emit "WORKING $n" ;;
        *)         emit "STATE $n $cur" ;;
      esac
      echo "$cur" > "$f.state"
      echo 0 > "$f.same"
      rm -f "$f.sig"
    fi

    if [ "$cur" = working ]; then
      sig=$(output_sig "$n")
      old=$(cat "$f.sig" 2>/dev/null || true)
      same=$(cat "$f.same" 2>/dev/null || echo 0)
      if [ -n "$old" ] && [ "$sig" = "$old" ]; then
        same=$((same + 1))
        [ "$same" -eq "$STALL" ] && emit "STALL $n $same"
      else
        same=0
      fi
      echo "$sig" > "$f.sig"
      echo "$same" > "$f.same"
    fi
  done

  if [ "$live" -eq 0 ]; then
    emit "WATCH end (no live workers)"
    exit 0
  fi
  sleep "$INTERVAL"
done
