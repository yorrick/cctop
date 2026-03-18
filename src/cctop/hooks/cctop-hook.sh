#!/bin/bash
# cctop hook - Captures Claude Code events for TUI monitoring
# Installed by: cctop install
set -e

KNOWN_PATHS=("/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin" "/usr/bin" "/bin")
for dir in "${KNOWN_PATHS[@]}"; do
  [ -d "$dir" ] && export PATH="$dir:$PATH"
done

JQ=$(command -v jq 2>/dev/null) || exit 0

CCTOP_DATA_DIR="${CCTOP_DATA_DIR:-$HOME/.cctop/data}"
EVENTS_FILE="$CCTOP_DATA_DIR/events.jsonl"
mkdir -p "$CCTOP_DATA_DIR"

input=$(cat)

hook_event_name=$(echo "$input" | "$JQ" -r '.hook_event_name // "unknown"')
session_id=$(echo "$input" | "$JQ" -r '.session_id // "unknown"')
transcript_path=$(echo "$input" | "$JQ" -r '.transcript_path // ""')

if command -v perl >/dev/null 2>&1; then
  timestamp=$(perl -MTime::HiRes=time -e 'printf "%.0f", time * 1000')
elif command -v python3 >/dev/null 2>&1; then
  timestamp=$(python3 -c 'import time; print(int(time.time() * 1000))')
else
  timestamp=$(($(date +%s) * 1000))
fi

case "$hook_event_name" in
  PreToolUse)
    tool_name=$(echo "$input" | "$JQ" -r '.tool_name // "unknown"')
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"tool_start\",\"tool\":\"$tool_name\",\"transcript_path\":\"$transcript_path\"}" >> "$EVENTS_FILE"
    ;;
  PostToolUse)
    tool_name=$(echo "$input" | "$JQ" -r '.tool_name // "unknown"')
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"tool_end\",\"tool\":\"$tool_name\",\"transcript_path\":\"$transcript_path\"}" >> "$EVENTS_FILE"
    ;;
  Stop)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"stop\",\"transcript_path\":\"$transcript_path\"}" >> "$EVENTS_FILE"
    ;;
  SessionStart)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"session_start\",\"transcript_path\":\"$transcript_path\"}" >> "$EVENTS_FILE"
    ;;
  SessionEnd)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"session_end\",\"transcript_path\":\"$transcript_path\"}" >> "$EVENTS_FILE"
    ;;
esac

exit 0
