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

Add `kb-mcp` as a custom connector with your URL, following Claude's guide:
[Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
On Team and Enterprise plans an Owner adds it once for everyone. Then connect it and sign in with
your normal company account.

Your `kb-mcp` URL must be reachable over the public internet: custom connectors connect from
Claude's cloud, not from your device.

## Claude Code

```bash
claude mcp add --transport http kb-mcp https://kb-mcp.<tenant>.unique.app/mcp
```

Then complete sign-in: run `/mcp` if you're already inside a session, or `claude mcp login kb-mcp`
from a bare shell if you're not. See Claude Code's [MCP documentation](https://code.claude.com/docs/en/mcp)
for the other options.

Optionally, install the `unique-kb-mcp` skill, which teaches Claude how to combine the tools
(scoping to a folder, checking metadata before filtering):

```bash
npx skills add Unique-AG/connectors
```

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

Open Cursor's MCP settings and sign in when prompted. See Cursor's
[MCP documentation](https://cursor.com/docs/mcp) for the other options.

## Related Documentation

- [User Guide](./user-guide.md): what you can do once connected
- [Overview](./README.md): what `kb-mcp` is and how it fits together
