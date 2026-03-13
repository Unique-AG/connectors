import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { normalizeContent } from '../utils/normalize-content';

const GetChatMessagesInputSchema = z.object({
  chatIdentifier: z.string().describe('Chat topic or member display name (case-insensitive)'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(20)
    .describe('Maximum number of messages to return (newest first)'),
  contentFormat: z
    .enum(['normalized', 'raw'])
    .default('normalized')
    .describe(
      'normalized converts HTML to readable text with @mentions and [attachment: name] placeholders. raw returns Teams HTML verbatim. Default: normalized',
    ),
  includeSystemMessages: z
    .boolean()
    .default(false)
    .describe(
      'System messages are event notifications (member added, call ended). Default false excludes them',
    ),
  timestampFormat: z
    .enum(['full', 'short', 'none'])
    .default('short')
    .describe(
      'full = ISO 8601 with ms, short = YYYY-MM-DD HH:mm, none = omit timestamps. Default: short',
    ),
  detail: z
    .enum(['standard', 'full'])
    .default('standard')
    .describe(
      'standard returns sender, content, and timestamp. full adds contentType (source format from Graph). Default: standard',
    ),
});

const GetChatMessagesOutputSchema = z.object({
  chatId: z.string(),
  chatTopic: z.string().nullable(),
  messages: z.array(
    z.object({
      id: z.string(),
      createdDateTime: z.string().optional(),
      senderDisplayName: z.string().nullable(),
      content: z.string(),
      contentType: z.string().optional(),
    }),
  ),
});

@Injectable()
export class GetChatMessagesTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  @Tool({
    name: 'get_chat_messages',
    title: 'Get Chat Messages',
    description:
      "Retrieve recent messages from a Microsoft Teams chat. Identify the chat by its topic (for group chats) or by the other person's display name (for 1:1 chats). Use list_chats first if unsure.",
    parameters: GetChatMessagesInputSchema,
    outputSchema: GetChatMessagesOutputSchema,
    annotations: {
      title: 'Get Chat Messages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'message-square',
    },
  })
  @Span()
  public async getChatMessages(
    input: z.infer<typeof GetChatMessagesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof GetChatMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_identifier', input.chatIdentifier);
    span?.setAttribute('limit', input.limit);

    this.logger.log(
      { userProfileId, chatIdentifier: input.chatIdentifier, limit: input.limit },
      'Getting chat messages',
    );

    const chat = await this.chatService.resolveChatByNameOrMember(
      userProfileId,
      input.chatIdentifier,
    );
    const messages = await this.chatService.getChatMessages(userProfileId, chat.id, input.limit);

    span?.setAttribute('result_count', messages.length);

    const filtered = input.includeSystemMessages
      ? messages
      : messages.filter((m) => m.senderDisplayName !== undefined);

    return {
      chatId: chat.id,
      chatTopic: chat.topic ?? null,
      messages: filtered.map((m) => this.mapMessage(m, input)),
    };
  }

  private mapMessage(
    m: MsChatMessage,
    input: z.infer<typeof GetChatMessagesInputSchema>,
  ): z.output<typeof GetChatMessagesOutputSchema>['messages'][number] {
    const content =
      input.contentFormat === 'normalized'
        ? normalizeContent(m.content, m.contentType, m.attachments)
        : m.content;

    const msg: z.output<typeof GetChatMessagesOutputSchema>['messages'][number] = {
      id: m.id,
      senderDisplayName: m.senderDisplayName ?? null,
      content,
    };

    if (input.timestampFormat !== 'none') {
      msg.createdDateTime =
        input.timestampFormat === 'full'
          ? m.createdDateTime
          : m.createdDateTime.replace('T', ' ').slice(0, 16);
    }

    if (input.detail === 'full') {
      msg.contentType = m.contentType;
    }

    return msg;
  }
}
