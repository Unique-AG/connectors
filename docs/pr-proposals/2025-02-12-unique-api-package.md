# PR Proposal

## Title

feat(unique-api): extract Unique API services into shared NestJS package

## Description

- Create `@unique-ag/unique-api` package with a factory-based architecture for multi-tenant usage -- `UniqueApiClientFactory` creates independent `UniqueApiClient` instances per tenant, each with its own auth state and GraphQL clients
- Extract GraphQL client, auth service (Zitadel OAuth + cluster_local), and domain services (scopes, files, users, groups, ingestion) from `sharepoint-connector`
- Bake in NestJS Logger for structured logging and OpenTelemetry metrics (via `nestjs-otel`) for request duration and error tracking
- Provide `UniqueApiModule` with `forRoot(config)` for single-tenant convenience and plain module import for multi-tenant factory usage
