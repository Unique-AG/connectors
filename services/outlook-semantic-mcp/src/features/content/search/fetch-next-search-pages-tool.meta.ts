import { createMeta } from '@unique-ag/mcp-server-module';
import { SEARCH_PAGE_STATUS_DESCRIPTION } from './search-emails-output.schema';

export const META = createMeta({
  icon: 'search',
  systemPrompt: `Continues searches started with \`search_emails\`. Every \`search_emails\` response lists its backend requests in \`pages\`; each entry has a \`status\` and, when it can be continued or retried, a \`cursorId\`.

  ## When to call it
  - Overview or listing questions ("all emails from last week", "summarise my conversation with Alice"): call this tool with every \`cursorId\` whose status is \`hasMore\` until \`hasMore\` is false, then answer. Do not answer from the first page alone.
  - Targeted questions: call it only when the answer was not found on the pages you already have.
  - Throttled or failed pages: retry by passing the same \`cursorId\` (after \`retryAfterSeconds\` for throttled pages).

  ## How to call it
  - Pass \`cursorIds\` exactly as returned — never edit, shorten, or invent them.
  - Each response returns new \`cursorId\`s. Use those for the next call, not the ones you already followed.
  - The same email can appear on pages of different requests. Treat results with the same \`msGraphMessageId\` as one email.

  ## Statuses
  ${SEARCH_PAGE_STATUS_DESCRIPTION}

  Before answering, tell the user when the results are incomplete: any page still \`throttled\` or \`failed\`, any \`ceilingReached\`, or \`hasMore\` still true.

  Results carry only partial content in \`text\`. To read an email in full, call \`open_email\` with the result's \`openEmailParams\`.`,
});
