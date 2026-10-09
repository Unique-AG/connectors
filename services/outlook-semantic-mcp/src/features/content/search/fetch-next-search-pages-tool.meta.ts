import { createMeta } from '@unique-ag/mcp-server-module';
import { SEARCH_CONFIG } from './search.config';
import { SEARCH_PAGE_STATUS_DESCRIPTION } from './search-emails-output.schema';

export const META = createMeta({
  icon: 'search',
  systemPrompt: `Continues searches started with \`search_emails\`. A \`search_emails\` call runs several backend requests (each semantic entry, and each KQL query per mailbox and folder) and lists them in \`pages\`. Each entry names its \`query\`, \`mailbox\` and \`folder\`, has a \`status\`, and has a \`cursorId\` when it can be continued or retried.

  ## When to call it
  - Overview or listing questions ("all emails from last week", "summarise my conversation with Alice"): call this tool with every \`cursorId\` whose status is \`hasMore\` until \`hasMore\` is false, then answer. Do not answer from the first page alone.
  - Targeted questions: call it when the answer was not found on the pages you already have. Use \`pages\` to pick the cursors: the mailbox or folder the user named, or the requests whose results came closest to the answer. If you cannot tell where the answer is, pass all \`hasMore\` cursors.
  - A short first page does not mean a request is exhausted. When a search fans out to many mailboxes and folders, its pages are smaller, and stay smaller here. Only the \`status\` tells you whether more exist.
  - Throttled or failed pages: retry ONCE by passing the same \`cursorId\` (after \`retryAfterSeconds\` for throttled pages). If it is still not delivered, stop retrying it. These pages do not count towards \`hasMore\`.

  ## How to call it
  - Pass up to ${SEARCH_CONFIG.maxCursorsPerFetch} \`cursorIds\` per call, exactly as returned — never edit, shorten, or invent them. With more cursors, call again with the rest.
  - Each response returns new \`cursorId\`s. Use those for the next call, not the ones you already followed.
  - Semantic pages are ranked by relevance: each next page holds less relevant passages than the one before, and a semantic search stops after ${SEARCH_CONFIG.semanticSearch.maxPages} pages.
  - The same email can appear on several pages: on pages of different requests, and on later semantic pages with further passages. Treat results with the same \`msGraphMessageId\` or \`uniqueContentId\` as one email.

  ## Statuses
  ${SEARCH_PAGE_STATUS_DESCRIPTION}

  Before answering, tell the user when the results are incomplete: they are complete only when every entry in \`pages\` is \`complete\`.

  Results carry only partial content in \`text\`. To read an email in full, call \`open_email\` with the result's \`openEmailParams\`.`,
});
