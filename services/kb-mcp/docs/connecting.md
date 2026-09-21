<!-- confluence-page-id: 2743763018 -->
<!-- confluence-space-key: PUBDOC -->

## Unique AI

If you use `kb-mcp` through Unique AI, there is nothing to configure. Your tenant admin connects it
once, and you sign in the first time it's used. See [Connecting](./user-guide.md#Connecting) in the
User Guide.

This page is for connecting a different MCP client, such as Claude or Cursor, directly to your
tenant's `kb-mcp` instance.

## What you need

Your tenant's `kb-mcp` URL, in the form:

```
https://kb-mcp.<tenant>.unique.app/mcp
```

Ask your IT administrator for the exact address if you don't have it.

`kb-mcp` uses OAuth, and every client below discovers and completes that login on its own once you
give it the URL. You never need a client ID, a client secret, or an API key.

## Claude Desktop / claude.ai

Your `kb-mcp` URL must be reachable over the public internet: custom connectors connect from
Claude's cloud, not from your device.

**If your organization is on a Team or Enterprise plan**, an Owner adds it once for everyone:

1. Owner navigates to Organization settings → Connectors, clicks "Add," hovers "Custom," selects
   "Web," and pastes the `kb-mcp` URL.
2. Everyone else finds it under their own Customize → Connectors (labeled "Custom"), clicks
   "Connect," and signs in with their normal company account.

**Otherwise**, add it yourself:

1. Navigate to Customize → Connectors and click "Add custom connector."
2. Enter a name and paste your `kb-mcp` URL.
3. Click "Add," then "Connect." Sign in with your normal company account and approve the
   connection.

## Claude Code

```bash
claude mcp add --transport http kb-mcp https://kb-mcp.<tenant>.unique.app/mcp
```

Then complete sign-in: run `/mcp` if you're already inside a session, or `claude mcp login kb-mcp`
from a bare shell if you're not.

## Cursor

Add this to `.cursor/mcp.json` in your project, or `~/.cursor/mcp.json` to make it available
everywhere:

```json
{
  "mcpServers": {
    "kb-mcp": {
      "url": "https://kb-mcp.<tenant>.unique.app/mcp"
    }
  }
}
```

Open Cursor's MCP settings and sign in when prompted.

## Related Documentation

- [User Guide](./user-guide.md): what you can do once connected
- [Overview](./README.md): what `kb-mcp` is and how it fits together
