export const serverInstructions = `
## Tool Selection Guidelines for OneNote MCP

### Important: Do not chain tools automatically
Each tool should only be called when the user's request directly requires it. Do not call search before creating a page. Do not call sync or verify status unless the user explicitly asks. Syncs happen automatically in the background.

### Searching OneNote Content
Use \`search_onenote\` only when the user asks to search, find, or look up existing content.

### Creating Content
- Use \`create_onenote_notebook\` to create a new notebook
- Use \`create_onenote_page\` to create a new page in a specific notebook and section
- Use \`update_onenote_page\` to append, prepend, or replace content on an existing page

After creating or updating content, a background sync runs automatically. Inform the user that the page will appear in search results within a couple of minutes.

### Managing Sync
- Use \`start_onenote_sync\` only when the user explicitly asks to sync or refresh
- Use \`stop_onenote_sync\` only when the user explicitly asks to stop syncing
- Use \`verify_onenote_sync_status\` only when the user explicitly asks about their sync status
`;
