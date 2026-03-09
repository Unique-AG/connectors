export const serverInstructions = `
## Tool Selection Guidelines for OneNote Connector

### Searching OneNote Content
Use \`search_onenote\` to find content across synced OneNote pages. You can filter by notebook name, section name, and date range.

### Creating Content
- Use \`create_onenote_notebook\` to create a new notebook
- Use \`create_onenote_page\` to create a new page in a specific notebook and section
- Use \`update_onenote_page\` to append, prepend, or replace content on an existing page

### Managing Sync
- Use \`start_onenote_sync\` to trigger an immediate sync of all notebooks
- Use \`stop_onenote_sync\` to stop syncing for the current user
- Use \`verify_onenote_sync_status\` to check the current sync status
`;
