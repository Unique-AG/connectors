#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$SCRIPT_DIR"

get_service_config() {
  case "$1" in
    agentic-outlook-mcp)
      echo "backend:pnpm watch:dev --filter=@unique-ag/agentic-outlook-mcp|frontend:pnpm watch:dev --filter=@unique-ag/agentic-outlook-mcp-web|python:cd services/python/sparse-embedding && uv run main.py|ngrok:cd services/agentic-outlook-mcp && pnpm dev:webhook"
      ;;
    outlook-mcp)
      echo "backend:pnpm watch:dev --filter=@unique-ag/outlook-mcp"
      ;;
    factset-mcp)
      echo "backend:pnpm watch:dev --filter=@unique-ag/factset-mcp"
      ;;
    sharepoint-connector)
      echo "backend:pnpm watch:dev --filter=@unique-ag/sharepoint-connector"
      ;;
    *)
      echo ""
      ;;
  esac
}

SERVICES=(
  "agentic-outlook-mcp"
  "factset-mcp"
  "outlook-mcp"
  "sharepoint-connector"
)

echo "Select a service to start:"
echo ""

for i in "${!SERVICES[@]}"; do
  SERVICE="${SERVICES[$i]}"
  CONFIG=$(get_service_config "$SERVICE")
  WINDOW_COUNT=$(echo "$CONFIG" | tr '|' '\n' | wc -l | tr -d ' ')
  echo "  $((i + 1))) $SERVICE ($WINDOW_COUNT windows)"
done

echo ""
read -p "Enter your choice (1-${#SERVICES[@]}): " choice

if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#SERVICES[@]}" ]; then
  echo "Invalid choice. Exiting."
  exit 1
fi

SERVICE="${SERVICES[$((choice - 1))]}"
SESSION_NAME="dev-$SERVICE"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo ""
  echo "Error: tmux session '$SESSION_NAME' already exists."
  read -p "Kill existing session and restart? (y/N): " kill_existing
  if [[ "$kill_existing" =~ ^[Yy]$ ]]; then
    tmux kill-session -t "$SESSION_NAME"
    echo "Killed existing session."
  else
    echo "Exiting."
    exit 1
  fi
fi

echo ""
echo "Starting service: $SERVICE"
echo "Session name: $SESSION_NAME"
echo ""

cd "$WORKSPACE_ROOT"

CONFIG=$(get_service_config "$SERVICE")
IFS='|' read -ra WINDOWS <<< "$CONFIG"

tmux new-session -d -s "$SESSION_NAME" -n "${WINDOWS[0]%%:*}"

WINDOW_NAME="${WINDOWS[0]%%:*}"
WINDOW_CMD="${WINDOWS[0]#*:}"
tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "cd $WORKSPACE_ROOT" C-m
tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$WINDOW_CMD" C-m

for i in "${!WINDOWS[@]}"; do
  if [ "$i" -eq 0 ]; then
    continue
  fi
  
  WINDOW_NAME="${WINDOWS[$i]%%:*}"
  WINDOW_CMD="${WINDOWS[$i]#*:}"
  
  tmux new-window -t "$SESSION_NAME" -n "$WINDOW_NAME"
  tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "cd $WORKSPACE_ROOT" C-m
  tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$WINDOW_CMD" C-m
done

echo "Service $SERVICE started successfully!"
echo ""
echo "To attach to the session: tmux attach -t $SESSION_NAME"
echo "To list windows: tmux list-windows -t $SESSION_NAME"
echo "To kill the session: tmux kill-session -t $SESSION_NAME"
echo ""
