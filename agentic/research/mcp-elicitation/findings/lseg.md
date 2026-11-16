# LSEG MCP (LSEG Financial Analytics)

| Field | Value |
|---|---|
| Vendor | London Stock Exchange Group (publisher "LSEG Financial Analytics"); official |
| Category | market-data |
| Tier | 2 |
| Source | closed (https://api.analytics.lseg.com/lfa/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://api.analytics.lseg.com/lfa/mcp (Claude org setup guide); https://api.analytics.lseg.com/lfa/mcp/server-cl (Anthropic directory listing) |
| Uses elicitation | unknown (docs don't mention it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- LSEG product page [lseg.com/…/lseg-mcp](https://www.lseg.com/en/solutions/ai-finance-solutions/lseg-mcp).
- LSEG articles: ["Supercharge Claude's financial skills"](https://www.lseg.com/en/insights/supercharge-claudes-financial-skills-with-lseg-data) (24 Feb 2026), ["The hidden economics of AI agents"](https://www.lseg.com/en/about-us/new-at-lseg/the-hidden-economics-of-ai-agents-and-how-lsegs-mcp-connector-helps-improve-token-efficiency) (17 Jul 2026), ["Scaling AI in Financial Services"](https://www.lseg.com/en/insights/scaling-ai-financial-services-with-lseg-trusted-ai-ready-content-mcp) (9 Oct 2025), [Anthropic partner page](https://www.lseg.com/en/solutions/ai-finance-solutions/anthropic).
- Microsoft connector reference, publisher "LSEG Financial Analytics", contact mcp-support@lseg.com ([learn.microsoft.com/connectors/lseg](https://learn.microsoft.com/en-us/connectors/lseg)).
- Anthropic's tutorial ([academy.claude.com](https://academy.claude.com/tutorials/using-lseg-for-financial-market-data-analysis)) and directory listing ([claude.com](https://claude.com/marketplace/connectors/london-stock-exchange-group)). Not LSEG pages.
- LSEG's technical MCP documentation is not public. The tutorial says to "Contact LSEG to get access to the MCP server and its technical documentation."

## Elicitation usages

None documented.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting the connector (not a tool call) | sign-in, outside MCP calls | auth-oauth | Directory listing: "Sign-in Required". LSEG FAQ: "Your existing LSEG licensed credentials govern access automatically", with no separate sign-up or API key. The sign-in flow itself is not described | docs don't say | [claude.com listing](https://claude.com/marketplace/connectors/london-stock-exchange-group), [lseg-mcp FAQ](https://www.lseg.com/en/solutions/ai-finance-solutions/lseg-mcp) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only: implied, not stated.** Tools are pricing, valuation and data retrieval calculators: `fx_spot_price`, `fx_forward_price`, `bond_price`, `bond_future_price`, `option_value`, `ir_swap`, `interest_rate_curve`, `credit_curve`, `inflation_curve`, `fx_forward_curve`, `fx_vol_surface`, `equity_vol_surface`, `qa_ibes_consensus`, `qa_macroeconomic`, `qa_company_fundamentals`, `insight_headlines`, `tscc_interday_summaries` ([Microsoft reference](https://learn.microsoft.com/en-us/connectors/lseg)). The Anthropic listing has 20 tools, adding `fixed_income_bond_reference`, `fixed_income_risk_analytics`, `yieldbook_scenario_calculation`. Descriptions say "Calculate…", "Access…", "Give…". No source says the server writes anything or that it is read-only. One LSEG article has a calculation result "ready to book", but booking happens outside the server ([Scaling AI](https://www.lseg.com/en/insights/scaling-ai-financial-services-with-lseg-trusted-ai-ready-content-mcp)).
- **Entitlements.** Content is "subject to customer entitlements" ([hidden economics](https://www.lseg.com/en/about-us/new-at-lseg/the-hidden-economics-of-ai-agents-and-how-lsegs-mcp-connector-helps-improve-token-efficiency)). Prerequisite: "Active LSEG data entitlements" ([Supercharge](https://www.lseg.com/en/insights/supercharge-claudes-financial-skills-with-lseg-data)). The MCP server "enforces issuer normalisation, entitlements" ([Scaling AI](https://www.lseg.com/en/insights/scaling-ai-financial-services-with-lseg-trusted-ai-ready-content-mcp)). It "embeds policy enforcement, access controls, and audit trails" ([Anthropic partner page](https://www.lseg.com/en/solutions/ai-finance-solutions/anthropic)). What happens on a request for unentitled content: docs don't say.
- **Usage limits.** The Microsoft connector has a throttle of 100 "API calls per connection" per 60 seconds ([Microsoft reference](https://learn.microsoft.com/en-us/connectors/lseg)). That may be the Power Platform wrapper's limit rather than the server's. Usage is described as "attributable, metered, and compliant with data rights" ([Scaling AI](https://www.lseg.com/en/insights/scaling-ai-financial-services-with-lseg-trusted-ai-ready-content-mcp)). LSEG "does not run the customer's model inference or control token usage" ([hidden economics](https://www.lseg.com/en/about-us/new-at-lseg/the-hidden-economics-of-ai-agents-and-how-lsegs-mcp-connector-helps-improve-token-efficiency)). The user is not asked before a call uses quota.
- **Disambiguation by search tools, not by asking.** Search and resolution tools help the agent find the right company, issuer, instrument, venue, benchmark or curve (paraphrase), and "help the agent orient itself before committing to a deeper retrieval" ([hidden economics](https://www.lseg.com/en/about-us/new-at-lseg/the-hidden-economics-of-ai-agents-and-how-lsegs-mcp-connector-helps-improve-token-efficiency)). The server "normalises instruments, validates priority, and returns clean, attributed data" ([Scaling AI](https://www.lseg.com/en/insights/scaling-ai-financial-services-with-lseg-trusted-ai-ready-content-mcp)). Anthropic's tutorial tells users to reference bonds by ISIN and specify tenors and valuation dates. No source describes the server asking the user to choose.
- **Customer-side control.** "Customers remain in control of the model, prompts, tools exposed and context passed forward" ([hidden economics](https://www.lseg.com/en/about-us/new-at-lseg/the-hidden-economics-of-ai-agents-and-how-lsegs-mcp-connector-helps-improve-token-efficiency)).

## Notes

- Tool counts differ: "ten specialised tools" in the Feb 2026 LSEG article, 17 in the Microsoft reference, 20 in Anthropic's listing.
- Two endpoint paths are published (`/lfa/mcp` and `/lfa/mcp/server-cl`). The docs don't say how they differ.
