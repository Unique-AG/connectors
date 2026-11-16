# S&P Global / Kensho LLM-ready API MCP ("S&P - Deterministic Retrieval"; also "Adaptive Retrieval")

| Field | Value |
|---|---|
| Vendor | S&P Global, built by Kensho; official |
| Category | market-data |
| Tier | 2 |
| Source | closed remote server (https://kfinance.kensho.com/integrations/mcp). A local server ships in the open-source `kensho-kfinance` package (https://github.com/kensho-technologies/kfinance @ 880585c); its code was not read, per scope |
| Language / SDK | local server: Python (`pip install kensho-kfinance`, `python -m kfinance.mcp`); remote: docs don't say |
| Hosted endpoint | https://kfinance.kensho.com/integrations/mcp (OAuth authorization code with dynamic client registration, Okta login) |
| Uses elicitation | unknown (docs don't mention it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- Kensho docs: [overview](https://docs.kensho.com/llmreadyapi/overview), [MCP overview](https://docs.kensho.com/llmreadyapi/mcp), [OAuth authorization code](https://docs.kensho.com/llmreadyapi/mcp/custom/oauth-authorization-code), [Claude setup](https://docs.kensho.com/llmreadyapi/mcp/third-party/claude), [local MCP](https://docs.kensho.com/llmreadyapi/mcp/custom/local-mcp), [FAQs](https://docs.kensho.com/llmreadyapi/faqs), [sample questions](https://docs.kensho.com/llmreadyapi/sample-questions).
- Kensho news: [MCP access expansion](https://kensho.com/news/kensho-llm-ready-api-expands-mcp-server-access-dataset-support-integrations), [ChatGPT app](https://kensho.com/news/s-p-global-delivers-trusted-financial-data-and-insights-to-customers-through-chatgpt), [Adaptive Retrieval](https://kensho.com/solutions/adaptive-retrieval).
- kfinance [README](https://github.com/kensho-technologies/kfinance/blob/main/README.md) (docs only) and [release v7.2.3](https://github.com/kensho-technologies/kfinance/releases/tag/v7.2.3).
- Anthropic's directory listing [claude.com/marketplace/connectors/s-p-global](https://claude.com/marketplace/connectors/s-p-global). Not an S&P page.
- The Kensho [API specification page](https://docs.kensho.com/llmreadyapi/api) rendered without content.

## Elicitation usages

None documented.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting in Claude (not a tool call) | browser OAuth (Okta), outside MCP calls | auth-oauth | After clicking Add, the user goes through an Okta browser login with the Kensho credentials emailed at sign-up. Claude Desktop reopens when sign-in completes. Only a Claude team owner can add the connector for the org | docs don't say | [Claude setup](https://docs.kensho.com/llmreadyapi/mcp/third-party/claude) |
| Local server started with no auth arguments | browser OAuth | auth-oauth | "Browser-based OAuth" is the fallback when no refresh token or key pair is given, "mainly for first-time or interactive setup" | docs don't say | [local MCP](https://docs.kensho.com/llmreadyapi/mcp/custom/local-mcp) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only: implied, not stated.** The FAQ calls the product "a data retrieval tool". All 22 tools in Anthropic's listing are `get_*`: `get_latest`, `get_info_from_identifiers`, `get_financial_statement_from_identifiers`, `get_prices_from_identifiers`, `get_transcript_from_key_dev_id`, `get_mergers_from_identifiers`, `get_competitors_from_identifiers` and others ([claude.com listing](https://claude.com/marketplace/connectors/s-p-global)). No write tool is listed anywhere.
- **Entitlements by dataset licence.** Users can ask the sample questions "Depending on which datasets users are licensed for" ([sample questions](https://docs.kensho.com/llmreadyapi/sample-questions)). The FAQ lists what the "Current subscription includes". The kfinance release v7.2.3 (23 Sep 2026) notes "Add RatingsPermission" and "update ratings error description" ([release](https://github.com/kensho-technologies/kfinance/releases/tag/v7.2.3)). That suggests per-dataset permissions, with an error when one is missing, but the docs do not describe what the user sees.
- **Tool access in the client.** The Claude guide recommends leaving all tools on, "unless you want to isolate select tools", and setting Tool access to "Tools already loaded" ([Claude setup](https://docs.kensho.com/llmreadyapi/mcp/third-party/claude)). The user controls this in the client, not the server.
- **Cost / quota.** Docs don't say. No rate limits are published on the pages read.
- **Disambiguation is left to the prompt.** "Queries require specific company names". The FAQ gives an identifier priority: "CapIQ Company ID", then ticker, ISIN, CUSIP, "Legal company name". "Using these specific identifiers will help ensure you get the most accurate and relevant data" ([FAQs](https://docs.kensho.com/llmreadyapi/faqs)). Without a company, "responses may be incomplete or ambiguous" ([sample questions](https://docs.kensho.com/llmreadyapi/sample-questions)). No source describes the server asking the user which company was meant.
- **Adaptive Retrieval** (premium tier): routing is automatic, with "No manual mapping of queries to specific data sources". Agents combine results "without manual orchestration" ([Adaptive Retrieval](https://kensho.com/solutions/adaptive-retrieval)). No confirmation or clarifying step is described.

## Notes

- The Deterministic Retrieval listing stresses "full customer control over orchestration, tool selection, and execution". Control sits with the client and the model, not with prompts from the server.
- The local server's refresh token "expire[s] after two weeks" and is "not advisable for use in production workflows". Key pair auth is recommended for production ([local MCP](https://docs.kensho.com/llmreadyapi/mcp/custom/local-mcp)).
- Open question: what a tool returns when the user lacks the dataset licence (error text, empty result, or the tool not being listed).
