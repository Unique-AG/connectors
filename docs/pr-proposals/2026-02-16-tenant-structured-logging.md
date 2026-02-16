# PR Proposal

## Ticket
UN-17171

## Title
feat(confluence-connector): add per-tenant structured logging via pino child loggers

## Description
- Add `getTenantLogger(ServiceClass)` helper that reads tenant from `AsyncLocalStorage` and creates a pino child logger with `{ tenantName, service }` structured fields
- Change `TenantContext.logger` from NestJS `Logger` to pino `Logger` with `tenantName` binding
- Refactor `TenantSyncScheduler` to use `getTenantLogger` for structured logs inside sync context
- Enables independent Grafana filtering by `tenantName` and `service` without regex
