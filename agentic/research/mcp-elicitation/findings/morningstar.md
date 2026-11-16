# Morningstar MCP Server

| Field | Value |
|---|---|
| Vendor | Morningstar; official |
| Category | market-data |
| Tier | 2 |
| Source | closed (https://mcp.morningstar.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.morningstar.com/mcp (Streamable HTTP; sign-in required) |
| Uses elicitation | unknown (no readable doc mentions it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- Morningstar developer docs: [MCP Server about](https://developer.morningstar.com/direct-web-services/documentation/morningstar-mcp-server/about), [Tools and Example Questions](https://developer.morningstar.com/direct-web-services/documentation/morningstar-mcp-server/tools-and-example-questions), [Workflow examples](https://developer.morningstar.com/direct-web-services/documentation/morningstar-mcp-server/workflow-examples). These pages are JavaScript-rendered and came back empty to a direct fetch. Statements from them below come from search-engine excerpts and are marked as such.
- The product page [morningstar.com/business/products/mcp-server](https://www.morningstar.com/business/products/mcp-server) also came back empty.
- Press releases, readable: [Microsoft AI tools](https://newsroom.morningstar.com/news/news-details/2025/Morningstar-Unleashes-AI-Ready-Investing-Insights-in-Microsoft-AI-Tools/default.aspx) (18 Nov 2025) and [ChatGPT apps, with PitchBook](https://newsroom.morningstar.com/news/news-details/2025/Morningstar-and-PitchBook-Bring-Trusted-Investing-Intelligence-to-Apps-in-ChatGPT/default.aspx) (17 Dec 2025).
- Anthropic's directory listing [claude.com/marketplace/connectors/morningstar](https://claude.com/marketplace/connectors/morningstar). Not a Morningstar page.

## Elicitation usages

None documented in anything readable.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting the connector (not a tool call) | sign-in, outside MCP calls | auth-oauth | Directory listing: sign-in required. The about page (search excerpt) says a licensed Morningstar account is required to connect and use the server. The flow is not described in readable text | docs don't say | [claude.com listing](https://claude.com/marketplace/connectors/morningstar), [about](https://developer.morningstar.com/direct-web-services/documentation/morningstar-mcp-server/about) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only: implied, not stated.** Six tools in Anthropic's listing: `morningstar-id-lookup-tool`, `morningstar-data-tool`, `morningstar-analyst-research-tool`, `morningstar-articles-tool`, `morningstar-screener-tool`, `morningstar-fund-holdings-tool`. Search excerpts of the tools page also mention Portfolio Analysis and Security Ownership tools. Every example question is a lookup ("Get the current P/B ratio for Microsoft stock", "Give me the Top 5 holdings in VOO and their weights"). No source mentions a write tool.
- **Entitlement by licence.** The tools page (search excerpt) tells users to ensure "the securities and data points you'd like to leverage are accessible through Morningstar's MCP Server and part of your license". The press releases say "secure, entitlement-based access" for "licensed users and firms" (18 Nov 2025). What a user sees when a security or data point is outside their licence: docs don't say.
- **Disambiguation by a lookup tool and by prompt advice.** The Data Tool needs a valid investment ID and data point ID from the ID Lookup tool. The tools page advises using tickers for funds and being specific about security and data point names, because names can be hard to tell apart (search excerpt, paraphrase). No source describes the server asking the user to choose between matches.
- **Cost / quota.** Docs don't say.

## Notes

- Morningstar is the parent of PitchBook (see `pitchbook.md`). They launched ChatGPT apps together, but they run separate MCP servers.
- Open question: the readable docs show no rate-limit or entitlement-error behaviour. The rendered developer pages may describe it.
