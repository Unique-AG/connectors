#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES_DIR="$SCRIPT_DIR/../../services"

SERVICES=(
  "agentic-outlook-mcp"
  "factset-mcp"
  "outlook-mcp"
  "sharepoint-connector"
)

echo "Select a service for which to start the docker-compose profile:"
echo ""

for i in "${!SERVICES[@]}"; do
  echo "  $((i + 1))) ${SERVICES[$i]}"
done

echo ""
read -p "Enter your choice (1-${#SERVICES[@]}): " choice

if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#SERVICES[@]}" ]; then
  echo "Invalid choice. Exiting."
  exit 1
fi

SERVICE="${SERVICES[$((choice - 1))]}"
ENV_FILE="$SERVICES_DIR/$SERVICE/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo ""
  echo "Warning: .env file not found at $ENV_FILE"
  read -p "Continue without env file? (y/N): " continue_without_env
  if [[ ! "$continue_without_env" =~ ^[Yy]$ ]]; then
    echo "Exiting."
    exit 1
  fi
  ENV_FLAG=""
else
  ENV_FLAG="--env-file $ENV_FILE"
fi

echo ""
echo "Starting docker-compose for service: $SERVICE"
echo "Command: docker-compose $ENV_FLAG --profile $SERVICE up -d"
echo ""

cd "$SCRIPT_DIR"
docker-compose $ENV_FLAG --profile "$SERVICE" up -d

echo ""
echo "Docker-compose profile for service $SERVICE started successfully!"

