# PitchBook Premium Connector (MCP)

| Field | Value |
|---|---|
| Vendor | PitchBook (a Morningstar company); official |
| Category | market-data |
| Tier | 2 |
| Source | closed (https://premium.mcp.pitchbook.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://premium.mcp.pitchbook.com/mcp (SSO sign-in) |
| Uses elicitation | unknown (docs don't mention it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- PitchBook help centre: [Getting started](https://pitchbook.com/help/getting-started-with-pitchbook-premium-connector), [for Claude](https://pitchbook.com/help/pitchbook-premium-connector-for-claude-by-anthropic), [Glean](https://pitchbook.com/help/pitchbook-premium-connector-glean), [Microsoft 365 Copilot](https://pitchbook.com/help/pitchbook-premium-connector-copilot), [Rogo](https://pitchbook.com/help/pitchbook-premium-connector-rogo), [prompt library](https://pitchbook.com/help/how-to-prompt-library-premium-connectors), [North by Cohere page](https://pitchbook.com/premium-connectors/cohere). pitchbook.com returned HTTP 403 to direct fetches. Statements from these pages come from search-engine excerpts and are marked as such.
- Readable: [Morningstar/PitchBook ChatGPT release](https://newsroom.morningstar.com/news/news-details/2025/Morningstar-and-PitchBook-Bring-Trusted-Investing-Intelligence-to-Apps-in-ChatGPT/default.aspx) (17 Dec 2025) and press coverage of the "PitchBook Data MCP" ([TechIntelPro](https://techintelpro.com/news/ai/enterprise-ai/pitchbook-launches-agentic-ai-assistant-and-data-mcp), 15 Oct 2026).
- Anthropic's directory listing [claude.com/marketplace/connectors/pitchbook](https://claude.com/marketplace/connectors/pitchbook). Not a PitchBook page.

## Elicitation usages

None documented.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting the connector (not a tool call) | SSO sign-in, outside MCP calls | auth-oauth | Claude guide (search excerpt): a Primary Owner or Owner enables the connector for the org first and needs a PitchBook seat. Each user then connects and authenticates via SSO | docs don't say | [for Claude](https://pitchbook.com/help/pitchbook-premium-connector-for-claude-by-anthropic) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only: implied, not stated.** Anthropic's listing has 23 tools, all `pitchbook_search`, `pitchbook_search_document_titles` or `pitchbook_get_*`. Examples: `pitchbook_get_profile`, `pitchbook_get_company_financials`, `pitchbook_get_deal_cap_table`, `pitchbook_get_valuation_estimates`, `pitchbook_get_vc_exit_predictor`, `pitchbook_get_similar_companies` ([claude.com listing](https://claude.com/marketplace/connectors/pitchbook)). No write tool is listed.
- **Per-call approval, from the client.** The Claude guide (search excerpt) says that by default "you'll need to approve each time Claude uses a PitchBook tool or data". The user can switch the connector from "Needs approval" to "Always allow" under Connectors → Manage connectors. This is Claude's tool-permission setting, documented by PitchBook. It is not a prompt the server sends.
- **Licence gate.** The Claude guide (search excerpt) requires "a seat-based, unlimited, or trial PitchBook license and single sign-on (SSO) credentials", plus a paid Claude plan. The North by Cohere page (search excerpt) says access follows existing PitchBook entitlements, so users only reach data their accounts are licensed for. What a user sees when a request falls outside their licence: docs don't say.
- **Usage caps, no prompt.** The Glean, Microsoft 365 Copilot and Rogo guides (search excerpts) list 150 tool calls per rolling 60 minutes and 300 per 24 hours. Excerpts of the Claude and ChatGPT pages don't show these figures. What happens on exceeding a cap: docs don't say. No source describes asking the user before a call uses quota.
- **Disambiguation by prompt guidance only.** Partner pages (search excerpt) say the prompt library gives example questions that "reduce ambiguity". Prompts use a `[Company Name]` placeholder. No source describes the server asking which company was meant. `pitchbook_search` returns candidates for the model to choose from.

## Notes

- PitchBook also runs a "PitchBook Essential" MCP (Perplexity, Mar 2026), and announced a "PitchBook Data MCP" in Oct 2026 that "connects a subset of PitchBook's verified dataset" into internal and third-party AI systems ([TechIntelPro](https://techintelpro.com/news/ai/enterprise-ai/pitchbook-launches-agentic-ai-assistant-and-data-mcp)). Neither has public tool-behaviour docs that we found.
- The only documented "ask before acting" step is the client's per-tool approval, set to on by default in PitchBook's Claude guide.
