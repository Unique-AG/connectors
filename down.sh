#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$SCRIPT_DIR"

SERVICES=(
  "agentic-outlook-mcp"
  "factset-mcp"
  "outlook-mcp"
  "sharepoint-connector"
)

RUNNING_SESSIONS=()
for SERVICE in "${SERVICES[@]}"; do
  SESSION_NAME="dev-$SERVICE"
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    RUNNING_SESSIONS+=("$SERVICE")
  fi
done

if [ ${#RUNNING_SESSIONS[@]} -eq 0 ]; then
  echo "No running dev sessions found."
  exit 0
fi

echo "Select a service to stop:"
echo ""

for i in "${!RUNNING_SESSIONS[@]}"; do
  echo "  $((i + 1))) ${RUNNING_SESSIONS[$i]}"
done

echo ""
read -p "Enter your choice (1-${#RUNNING_SESSIONS[@]}): " choice

if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#RUNNING_SESSIONS[@]}" ]; then
  echo "Invalid choice. Exiting."
  exit 1
fi

SERVICE="${RUNNING_SESSIONS[$((choice - 1))]}"
SESSION_NAME="dev-$SERVICE"

echo ""
echo "Stopping service: $SERVICE"
echo "Session name: $SESSION_NAME"
echo ""

tmux kill-session -t "$SESSION_NAME"

echo "Service $SERVICE stopped successfully!"
echo ""
