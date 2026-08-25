import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { AttributeUpstreamErrors } from '../../utils/attribute-upstream-errors.decorator';
import { MessageOutputSchema } from '../chat.dtos';
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
        `Results per page, 1-${MAX_PAGE_SIZE}. Default: ${MAX_PAGE_SIZE}. Each result costs an extra fetch, so ask for fewer when you can.`,
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
      message: MessageOutputSchema.optional(),
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
      'Search Microsoft Teams messages by keyword across 1:1 chats, group chats and channels. ' +
      'Narrow the search by sender, recipient, mentions, date range, attachments, read state and mention state. ' +
      "Each row names its container in source: 'channel' carries a team id and a channel id, 'chat' carries a chat id, 'unknown' otherwise. " +
      'Keep the rows whose source you want. ' +
      'Each row also carries the full message under message, with its body, sender, mentions, attachments and reactions. ' +
      'Message bodies are Teams HTML. ' +
      "message is absent for rows whose source is 'unknown' and for replies inside a channel thread. " +
      'senderDisplayName, summary and webUrl come straight from the search index. ' +
      'Page by adding returnedCount to offset while moreResultsAvailable is true.',
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
