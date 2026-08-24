import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { AttributeUpstreamErrors } from '../../utils/attribute-upstream-errors.decorator';
import { SearchService } from '../search.service';

// Not a Graph limit: Microsoft caps a search page at 25 for the `message` and
// `event` entities only, never for `chatMessage`. 25 is a product choice — every
// hit is hydrated with one extra Graph call, so the page size is also the N of
// that fan-out.
const MAX_PAGE_SIZE = 25;

export const SearchMessagesInputSchema = z
  .object({
    query: z
      .string()
      .trim()
      .min(1)
      .optional()
      .describe('Free-text keywords to match in message content. Multi-word terms are quoted.'),
    from: z
      .string()
      .trim()
      .min(1)
      .optional()
      .describe('Sender name or email (KQL `from:`). Matches the message author.'),
    to: z.string().trim().min(1).optional().describe('Recipient name or email (KQL `to:`).'),
    mentions: z
      .uuid()
      .optional()
      .describe('User object id (GUID) of a mentioned user; dashes are stripped automatically.'),
    sentAfter: z.iso
      .date()
      .optional()
      .describe('Only messages sent on or after this date (ISO date, e.g. 2024-01-15).'),
    sentBefore: z.iso
      .date()
      .optional()
      .describe('Only messages sent on or before this date (ISO date, e.g. 2024-01-31).'),
    hasAttachment: z
      .boolean()
      .optional()
      .describe('Restrict to messages with (true) or without (false) attachments.'),
    isRead: z.boolean().optional().describe('Restrict to read (true) or unread (false) messages.'),
    isMentioned: z
      .boolean()
      .optional()
      .describe(
        'Restrict to messages where the signed-in user is (true) or is not (false) mentioned.',
      ),
    offset: z
      .number()
      .int()
      .min(0)
      .default(0)
      .describe('Number of results to skip for pagination (maps to Graph `from`). Default: 0'),
    size: z
      .number()
      .int()
      .min(1)
      .max(MAX_PAGE_SIZE)
      .default(MAX_PAGE_SIZE)
      .describe(
        `Maximum number of results to return per page (1-${MAX_PAGE_SIZE}). Every hit costs one extra Graph call, so ask for fewer when a narrow answer will do. Default: ${MAX_PAGE_SIZE}`,
      ),
  })
  .refine(
    (data) =>
      data.query !== undefined ||
      data.from !== undefined ||
      data.to !== undefined ||
      data.mentions !== undefined ||
      data.sentAfter !== undefined ||
      data.sentBefore !== undefined ||
      data.hasAttachment !== undefined ||
      data.isRead !== undefined ||
      data.isMentioned !== undefined,
    {
      message:
        'At least one search criterion (query, from, to, mentions, sentAfter, sentBefore, hasAttachment, isRead, or isMentioned) must be provided.',
    },
  );

const SearchMessagesOutputSchema = z.object({
  messages: z.array(
    z.object({
      id: z.string(),
      source: z.enum(['chat', 'channel', 'unknown']),
      chatId: z.string().nullable(),
      teamId: z.string().nullable(),
      channelId: z.string().nullable(),
      senderDisplayName: z.string().nullable(),
      summary: z.string().nullable(),
      content: z.string().optional(),
      createdDateTime: z.string().nullable(),
      webUrl: z.string().nullable(),
    }),
  ),
  // Graph reports `total` per page, not total matches across the corpus, so we
  // expose the page count and a pagination flag instead.
  returnedCount: z.number(),
  moreResultsAvailable: z.boolean(),
});

@Injectable()
export class SearchMessagesTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly searchService: SearchService,
  ) {}

  @Tool({
    name: 'search_messages',
    title: 'Search Messages',
    description:
      "Search Microsoft Teams messages by keyword across 1:1 chats, group chats, and channels in a single query, using the Microsoft Search API. Supports filters on sender, recipient, mentions, date range, attachments, and read/mention state. Graph offers no way to scope a search to chats or to channels, so every hit is returned and narrowing to one kind is your job: a hit is 'channel' only when it carries both a team id and a channel id, 'chat' when it carries a chat id, and 'unknown' otherwise. Every addressable hit is then fetched to fill in its message body, so a follow-up get_chat_messages or get_channel_messages call is normally unnecessary. content is always normalized plain text, never HTML: a message carrying no text of its own reads as a placeholder such as [image], [card] or [attachment: name], and a deleted message reads as [deleted] — treat those as descriptions, not as what was written. content is absent when the hit names no container, when the fetch fails (denied, throttled, or gone), and for a reply inside a channel thread — Graph addresses a reply under its parent post and the search index does not name that post, so a reply's body cannot be retrieved by any tool here. webUrl may be an Outlook Web link rather than a Teams deep link, because a search hit is an Exchange projection of the message. Paginate by advancing offset by returnedCount, stopping when moreResultsAvailable is false or returnedCount is 0.",
    parameters: SearchMessagesInputSchema,
    outputSchema: SearchMessagesOutputSchema,
    annotations: {
      title: 'Search Messages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'search',
    },
  })
  @AttributeUpstreamErrors()
  @Span()
  public async searchMessages(
    input: z.infer<typeof SearchMessagesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SearchMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Searching messages');

    const result = await this.searchService.searchMessages(userProfileId, {
      query: input.query,
      from: input.from,
      to: input.to,
      mentions: input.mentions,
      sentAfter: input.sentAfter,
      sentBefore: input.sentBefore,
      hasAttachment: input.hasAttachment,
      isRead: input.isRead,
      isMentioned: input.isMentioned,
      offset: input.offset,
      size: input.size,
    });

    span?.setAttribute('result_count', result.returnedCount);

    return result;
  }
}
