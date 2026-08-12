# PR Proposal

## Ticket

UN-23554

## Title

`feat(outlook-semantic-mcp,proxy,ci,deps): add forward proxy support`

Scopes verified against `.gitcommitizen`: `packages/proxy/**` → new `proxy` scope (added by this PR),
`services/outlook-semantic-mcp/**` → `outlook-semantic-mcp`, `.gitcommitizen` → `ci`,
`pnpm-lock.yaml` → `deps`.

## Description

- Extract `@unique-ag/proxy` (`ProxyModule`, `ProxyService`, `PROXY_*` config schema) from the
  confluence-connector implementation, and route all nine outbound call sites in
  `outlook-semantic-mcp` through it — Graph SDK, token refresh, Unique API, health checks, and the
  attachment/blob upload paths.
- Proxy the `passport-microsoft` login flow, which the ticket missed: it runs on Node's core `https`
  agent and is unreachable by an undici dispatcher, so without this a proxied deployment could never
  complete a login. Handled via `oauth`'s `setAgent()` and `https-proxy-agent`, with no change to
  `@unique-ag/mcp-oauth`.
- Compose `interceptors.retry()` and `interceptors.redirect()` back onto the dispatcher passed to
  `UniqueApiModule`. `unique-api` only applies them when no dispatcher is supplied, so passing one
  would otherwise have silently dropped both — including when no proxy is configured.
- Add the Helm `proxyConfig` block, ConfigMap template and chart tests, plus `.env.example` and
  operator documentation, matching the SharePoint connector's env var names and semantics.
- Delete the unused `HttpClientModule`, which composed retry/redirect on a non-proxied agent and
  would have become a silent proxy bypass.
- `sharepoint-connector` and `confluence-connector` are untouched; migrating them onto the new
  package is a tracked follow-up.
