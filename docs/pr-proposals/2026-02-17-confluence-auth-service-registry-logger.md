# PR Proposal

## Ticket
UN-17171

## Title
refactor(confluence-connector): route confluence auth logging through service registry logger

## Description
- Move Confluence auth logger ownership to `ServiceRegistry`-driven tenant wiring.
- Inject logger into Confluence auth factory and strategies instead of creating local logger instances.
- Preserve existing Confluence auth behavior while enforcing consistent structured logging context keys (`tenantName`, `service`).
- Keep the change scoped to Confluence auth, with a reusable pattern for future service-wide adoption.
