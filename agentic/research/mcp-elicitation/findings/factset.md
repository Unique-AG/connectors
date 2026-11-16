# FactSet AI-Ready Data MCP (and Portfolio Analytics MCP)

| Field | Value |
|---|---|
| Vendor | FactSet Research Systems; official |
| Category | market-data |
| Tier | 1 |
| Source | closed (https://mcp.factset.com/content/v1) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.factset.com/content/v1 (sign-in required) |
| Uses elicitation | unknown (no readable doc mentions it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- FactSet's MCP docs, [developer.factset.com/mcp/factset-ai-ready-data-mcp](https://developer.factset.com/mcp/factset-ai-ready-data-mcp) and [developer.factset.com/mcp](https://developer.factset.com/mcp). Both are JavaScript-rendered and came back as an empty shell (title only), so none of their content is used here.
- FactSet marketing pages that also came back empty: [factset.com/lp/model-context-protocol](https://www.factset.com/lp/model-context-protocol), [product blog "MCP vs. RAG vs. Plug-Ins"](https://www.factset.com/product-blog/overviews/mcp-vs-rag-vs-plug-ins), [Portfolio Analytics MCP marketplace page](https://www.factset.com/marketplace/catalog/product/portfolio-analytics-mcp), [GenAI Governance and Security Policy](https://www.factset.com/GenAI-Governance-and-Security). Where cited below, their text comes from search-engine excerpts and is marked as such.
- Launch release, 16 Dec 2025 ([Yahoo Finance copy](https://finance.yahoo.com/news/factset-meets-demand-ai-ready-110500592.html); the investor.factset.com original returned 403).
- Gemini Enterprise release, 25 Aug 2026 ([Google Cloud press corner](https://www.googlecloudpresscorner.com/2026-08-25-FactSets-AI-Ready-MCP-Integration-Now-Live-in-Gemini-Enterprise-for-Financial-Services)).
- Anthropic's directory listing ([claude.com/marketplace/connectors/factset](https://claude.com/marketplace/connectors/factset)). Not a FactSet page.

## Elicitation usages

None documented in anything readable.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting the connector (not a tool call) | sign-in, outside MCP calls | auth-oauth | Anthropic's listing says "Sign-in Required". The flow is not described in a readable FactSet doc | docs don't say | [claude.com listing](https://claude.com/marketplace/connectors/factset) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only: implied, not stated.** All 23 tools in Anthropic's listing are dataset accessors: `FactSet_Fundamentals`, `FactSet_EstimatesConsensus`, `FactSet_GlobalPrices`, `FactSet_Ownership`, `FactSet_MergersAcquisitions`, `FactSet_People`, `FactSet_CompanyScreener`, `FactSet_EntityReference`, `FactSet_BondPrices` and others ([claude.com listing](https://claude.com/marketplace/connectors/factset)). The launch release describes "access to nine key datasets". No readable source says whether any tool writes. No read/write labels are shown.
- **Entitlements enforced per user.** Search excerpt of FactSet's product blog: "FactSet MCP is provisioned at the user level and is entitlement-aware, respecting each user's permissions" ([product blog](https://www.factset.com/product-blog/overviews/mcp-vs-rag-vs-plug-ins)). Search excerpts of the governance policy and the 2025 Impact Report say FactSet stores and enforces individual access rights, including third-party data entitlements, across delivery channels including MCP ([policy](https://www.factset.com/GenAI-Governance-and-Security)). What a user sees when a request hits data they are not entitled to (error, empty result, hidden tool): docs don't say.
- **Governance and audit.** The launch release calls it "direct, governed, production access to financial intelligence, designed for AI systems". A search excerpt of the LP page mentions an activity record kept for regulatory requirements ([LP](https://www.factset.com/lp/model-context-protocol)). No per-call user approval is described.
- **Cost / quota.** Docs don't say. No rate limits or usage prompts found.
- **Disambiguation.** Docs don't say. `FactSet_EntityReference` exists by name. Whether the server or the model asks the user to pick an entity is not described.
- **Gemini Enterprise.** The Aug 2026 release says "no additional login" in that deployment, which uses "custom-deployed connectors". The suite there includes portfolio analytics, scenario analysis, collateral and hedge analytics, and bond total return calculations. Read/write status is not stated.

## Notes

- **Portfolio Analytics MCP** (limited release, announced 26 Jun 2026): press coverage describes "pre-calculated, approved analytics" (performance, attribution, risk) ([Nasdaq copy of the release](https://www.nasdaq.com/press-release/factset-expands-model-context-protocol-suite-portfolio-analytics-2026-06-26), timed out on fetch; wording via search excerpt). Whether it starts calculations on demand, and whether those cost anything or need confirmation: docs don't say.
- Tier 1, but evidence is thin. FactSet's developer portal renders client-side, and we could not read it without a browser. Open question: what the rendered portal says about tools, entitlement errors and limits.
