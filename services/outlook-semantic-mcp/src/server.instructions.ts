export const serverInstructions = `
## Tool Selection Guidelines for Outlook MCP

### Inbox Connection
- If the inbox is not connected, suggest the user run \`reconnect_inbox\` before attempting any other operations.

### Sync Status
- Use \`sync_progress\` to check the current sync status before querying emails; if the result shows \`fullSyncState\` is not \`'ready'\`, \`liveCatchUpState\` is not \`'ready'\`, or \`ingestionStats\` contains pending items, inform the user that email ingestion is still in progress and results may be partial before proceeding with search.
- The \`dateWindow\` in sync stats shows the range of emails fetched so far (newest/oldest created and last modified timestamps).

### Search Results and Incomplete Ingestion
- When \`search_emails\` returns a \`syncWarning\` field, relay that warning message to the user so they know results may not reflect all emails.
`;
