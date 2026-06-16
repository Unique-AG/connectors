import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { SearchService } from '../search.service';

const SearchMessagesInputSchema = z
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
    source: z
      .enum(['chat', 'channel', 'all'])
      .default('all')
      .describe(
        'Filter results by container. Applied after the search (entityType is always chatMessage), so a non-all value shrinks the returned page. Default: all',
      ),
    detail: z
      .enum(['summary', 'full'])
      .default('summary')
      .describe(
        'summary returns the hit snippet only (1 Graph call, fast). full hydrates each hit with its message body (one extra Graph call per hit). Default: summary',
      ),
    contentFormat: z
      .enum(['normalized', 'raw'])
      .default('normalized')
      .describe(
        'Only applies when detail=full. normalized converts HTML to readable text; raw returns Teams HTML verbatim. Default: normalized',
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
      .max(50)
      .default(25)
      .describe('Maximum number of results to return per page. Default: 25'),
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
      source: z.enum(['chat', 'channel']),
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
      'Search Microsoft Teams messages by keyword across 1:1 chats, group chats, and channels in a single query, using the Microsoft Search API. Supports identity and scope filters (sender, recipient, mentions, date range, attachments, read/mention state). Results are snippets by default; set detail=full to retrieve message bodies. Paginate with offset + moreResultsAvailable.',
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
    span?.setAttribute('source', input.source);
    span?.setAttribute('detail', input.detail);

    this.logger.log(
      { userProfileId, source: input.source, detail: input.detail },
      'Searching messages',
    );

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
      source: input.source,
      detail: input.detail,
      contentFormat: input.contentFormat,
      offset: input.offset,
      size: input.size,
    });

    span?.setAttribute('result_count', result.returnedCount);

    return result;
  }
}
