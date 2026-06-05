# Unreliable Email Retrieval — Manual Recall Testing

## Purpose

This test verifies whether the ingestion pipeline surfaces emails that are present in the mailbox, given that the agent has already determined the correct search parameters. It tests recall (are the right emails found?) rather than search quality (did the agent phrase the query well?).

## How to run

Use [MCP Inspector](https://github.com/modelcontextprotocol/inspector) connected to the outlook-semantic-mcp server, authenticated as the mailbox owner you want to test. Call the `admin_ops` tool with `search_recall_check` as the sub-tool.

### Example — tester2 inbox

The following input checks two emails known to exist in the tester2 mailbox:

```json
{
  "tool": {
    "type": "search_recall_check",
    "params": {
      "cases": [
        {
          "id": "q1-report",
          "search": {
            "search": "Q1 financial report",
            "mailbox": "tester2@example.com"
          }
        },
        {
          "id": "onboarding-invite",
          "graphFilter": "from/emailAddress/address eq 'hr@example.com'",
          "search": {
            "search": "onboarding schedule new hire",
            "mailbox": "tester2@example.com",
            "conditions": [
              {
                "fromSenders": ["hr@example.com"]
              }
            ]
          }
        }
      ]
    }
  }
}
```

Each case has:
- `id` — a label used to identify the case in the result
- `search` — the same payload the agent would pass to `search_emails`, including `search` (query string), optional `mailbox`, optional `conditions`, and optional `limit`
- `graphFilter` / `graphSearch` — optional raw Microsoft Graph OData filter/search strings to scope the ground-truth fetch independently of the semantic search

## Splitting long test runs

A single `search_recall_check` call accepts between 1 and 20 cases. If your test suite is large, the request will time out. Split it into multiple calls of ≤ 20 cases each and aggregate the results manually.
