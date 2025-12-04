# Agentic Outlook MCP Web

When running the frontend for the first time, you need to register the web client with the OAuth server.

To do this, run the following command:

```bash
pnpm register-client
```

This will register the web client with the OAuth server and print the client ID.

You need to update the `VITE_OAUTH_CLIENT_ID` in the `.env` file with the client ID.