import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';

const MICROSOFT_GRAPH_INSTRUCTIONS = `
Emails are searched directly via Microsoft Graph KQL —
no ingestion, sync, or knowledge base is involved.
All tools operate directly against the live mailbox.
`;

const MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS = `
## Tool Selection Guidelines for Outlook MCP

### Inbox Connection
- If the inbox is not connected, suggest the user run \`reconnect_inbox\` before attempting any other operations.

### Search Results and Incomplete Ingestion
- When \`search_emails\` returns a \`syncWarning\` field, relay that warning message to the user so they know results may not reflect all emails.
`;

export function buildServerInstructions(): string {
  return isMicrosoftGraphBackend()
    ? MICROSOFT_GRAPH_INSTRUCTIONS
    : MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS;
}
