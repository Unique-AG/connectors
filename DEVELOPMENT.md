# Development Service Launcher

Scripts to easily start and stop development services with multiple dependencies using tmux.

## Usage

### Starting a Service

```bash
./up.sh
```

This will:
1. Show a list of available services
2. Start a detached tmux session named `dev-<service-name>`
3. Create named windows for each dependency (backend, frontend, python, etc.)
4. Run the appropriate commands in each window

### Stopping a Service

```bash
./down.sh
```

This will:
1. Show a list of currently running dev sessions
2. Kill the selected tmux session

### Managing Sessions

After starting a service, you can:

```bash
# Attach to the session
tmux attach -t dev-agentic-outlook-mcp

# List all windows in the session
tmux list-windows -t dev-agentic-outlook-mcp

# Switch between windows (when attached)
Ctrl+b 0  # Go to window 0
Ctrl+b 1  # Go to window 1
Ctrl+b n  # Next window
Ctrl+b p  # Previous window

# Detach from session (when attached)
Ctrl+b d

# Kill a specific session
tmux kill-session -t dev-agentic-outlook-mcp

# List all sessions
tmux ls
```

## Adding a New Service

To add a new service, edit the `get_service_config()` function in `up.sh`:

```bash
get_service_config() {
  case "$1" in
    my-new-service)
      echo "window1:command1|window2:command2|window3:command3"
      ;;
    # ... other services ...
  esac
}
```

Then add the service name to the `SERVICES` array in both `up.sh` and `down.sh`:

```bash
SERVICES=(
  "agentic-outlook-mcp"
  "factset-mcp"
  "my-new-service"  # Add your service here
  "outlook-mcp"
  "sharepoint-connector"
)
```

### Format

The format is: `windowName:command|windowName:command|...`

- **windowName**: Name displayed in tmux (e.g., `backend`, `frontend`, `python`)
- **command**: Shell command to run in that window
- Separate multiple windows with `|` (pipe character)

### Examples

Single window service:
```bash
simple-service)
  echo "backend:pnpm watch:dev --filter=@unique-ag/simple-service"
  ;;
```

Multi-window service:
```bash
complex-service)
  echo "backend:pnpm watch:dev --filter=@unique-ag/backend|frontend:pnpm watch:dev --filter=@unique-ag/frontend|worker:cd services/worker && python main.py"
  ;;
```

## Current Services

- **agentic-outlook-mcp** (3 windows)
  - backend: NestJS backend with hot reload
  - frontend: React frontend with Vite
  - python: Sparse embedding gRPC service

- **outlook-mcp** (1 window)
  - backend: NestJS backend with hot reload

- **factset-mcp** (1 window)
  - backend: NestJS backend with hot reload

- **sharepoint-connector** (1 window)
  - backend: NestJS backend with hot reload

## Notes

- All commands run from the workspace root directory
- Sessions are named `dev-<service-name>` to avoid conflicts
- If a session already exists, you'll be prompted to kill and restart it
- The scripts require `tmux` to be installed
- Compatible with bash 3.x+ (including the default bash on macOS)
