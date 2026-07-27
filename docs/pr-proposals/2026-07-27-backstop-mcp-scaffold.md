# PR Proposal

## Ticket
UN-22647

## Title
feat(backstop-mcp): scaffold FastMCP service shell

## Description
- Add new `services/backstop-mcp` FastMCP-based service scaffold (no domain tools yet) ahead of the Backstop REST API investigation.
- Wire structlog logging, dotenv config loading, and OpenTelemetry metrics with a Prometheus exporter, following the pattern piloted in the unmerged `edgar-mcp` branch.
- Add `/health` and `/probe` operational endpoints via FastMCP's `custom_route`, no FastAPI wrapper.
- Add Dockerfile + minimal Helm chart deployment scaffolding, and register the service scope in `.gitcommitizen`.
