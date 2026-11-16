# Sentry MCP (hosted, mcp.sentry.dev)

| Field | Value |
|---|---|
| Vendor | Sentry; official (hosted service; the open repo is reviewed in `sentry.md`) |
| Category | dev-platform |
| Tier | 3 |
| Source | closed view (https://mcp.sentry.dev); deployed from the open repo in `sentry.md` |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.sentry.dev/mcp, optionally `/mcp/{organizationSlug}` or `/mcp/{organizationSlug}/{projectSlug}` |
| Uses elicitation | unknown (docs never mention elicitation) |
| Mechanism | docs don't say |
| Evidence type | docs only |

Sources:
- Product docs: [docs.sentry.io/product/sentry-mcp](https://docs.sentry.io/product/sentry-mcp/) redirects (301) to [mcp.sentry.dev](https://mcp.sentry.dev/). Its text is the same as [mcp.sentry.dev/llms.txt](https://mcp.sentry.dev/llms.txt) ("product page").
- Repo docs (markdown, not code), where the product page has nothing: [README](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/README.md), [docs/operations/security.md](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/docs/operations/security.md), [docs/cloudflare/oauth-architecture.md](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/docs/cloudflare/oauth-architecture.md).

## Elicitation usages

None documented. The product page is short. It covers OAuth sign-in, URL scoping, `?experimental=1` and client setup. It says nothing about confirmations, approvals, elicitation, or destructive tools. The repo docs listed above don't mention elicitation either.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none documented | – | – | – | – | – |

Purpose by purpose:
- **Destructive operations:** the product page doesn't list tools. It only says the server is for "searching errors, analyzing performance, triaging issues, reading documentation, and managing projects". The docs mention no confirmation for any write.
- **Disambiguation (org / project):** handled by URL scoping, not by asking during a call. "When scoped, tools automatically default to the constrained org/project and unnecessary discovery tools are hidden. Scoping to a project is recommended when possible." (product page). Without scoping, docs don't say how the org or project is chosen.
- **Cost confirmation, secret entry:** docs don't say.

## Fallback without client elicitation support

Not applicable, since no elicitation is documented.

## Other human-in-the-loop mechanisms

- **Sign-in.** "All connections use OAuth. The first connection will trigger an authentication flow to connect to your Sentry account." (product page).
- **Consent screen with skill selection** (repo docs only). The hosted OAuth flow shows an MCP consent screen before Sentry's own: "Show MCP consent screen" / "Approve MCP permissions", described as "Dual consent: Users approve both MCP permissions and Sentry access" (oauth-architecture.md). "Our approval UI collects the MCP-side permissions for the session", and "Tools are registered only when their skill set is enabled" (security.md). Cancelling sends the client `error=access_denied` (oauth-architecture.md). This is a one-time grant at connect time, not a per-action confirmation.
- **URL constraints.** The `/mcp/{org}/{project}` path narrows every call (product page).
- **Direct-token mode.** With a `Sentry-Bearer` header, the session "defaults to all active MCP skills" and can be narrowed with `?skills=` / `?disable-skills=`. These sessions "do not get OAuth consent-screen skill selection" (README, security.md).
- **Stated design intent.** "Sentry's MCP service is primarily designed for human-in-the-loop coding agents" (README). Approval of individual calls is left to the client.
- **Annotations:** docs don't say. (`sentry.md` covers what the code does.)

## Notes

- The public product docs for the hosted service are a single page. Most of the behaviour here comes from repo markdown, which documents the same deployed service. None of the documentation describes the server asking the user anything during a tool call.
