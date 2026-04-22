# PR Proposal

## Ticket

UN-19205

## Title

fix(confluence-connector): sanitize errors in logging

## Description

closes https://unique-ch.atlassian.net/browse/UN-19205

- Extract `sanitizeError` and `normalizeError` from `sharepoint-connector` into the shared `@unique-ag/utils` package so future connectors can reuse them. SharePoint is left untouched in this PR.
- Apply `err: sanitizeError(error)` to every raw-error log site in the Confluence connector, starting with `scope-management.service.ts` (the site named in the ticket) and covering `ingestion.service`, `confluence-content-fetcher`, `confluence-synchronization.service`, `tenant-sync.scheduler`, `oauth2lo-auth.strategy`, and `rate-limited-http-client`.
- Extend the sanitisation into the shared dependency chain used by Confluence: `packages/unique-api` (`unique-graphql.client`, `unique-http.client`, `files.service`, `unique-auth`) and `packages/utils` (`processInBatches`). These close leaks that fire upstream of the consumer-side catch blocks.
- Prevents `graphql-request` `ClientError` instances from leaking raw request variables (tokens, internal URLs, content keys) into logs via `error.message` and `error.stack`.
- Keeps the pino `err:` log key unchanged to preserve existing Loki queries and dashboards. Sanitization runs before pino, so the serializer sees an already-cleaned plain object.
- Ports the SharePoint `normalize-error.spec.ts` into `@unique-ag/utils`. No new service-level tests: call-site changes are mechanical and existing service tests cover the surrounding flows.
