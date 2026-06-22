import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { BadRequestException, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { normalizeContent } from '../utils/normalize-content';

const GetChatMessagesInputSchema = z
  .object({
    chatId: z
      .string()
      .optional()
      .describe(
        'Exact chat id from list_chats. Preferred — targets one chat unambiguously. Provide this or chatIdentifier.',
      ),
    chatIdentifier: z
      .string()
      .optional()
      .describe(
        'Chat topic or member display name (case-insensitive). Fallback when you do not have the chatId; may match multiple chats.',
      ),
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
  })
  .refine((d) => d.chatId !== undefined || d.chatIdentifier !== undefined, {
    message: 'Provide either chatId (from list_chats) or chatIdentifier (topic or member name).',
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
      "Retrieve recent messages from a Microsoft Teams chat. Prefer passing the chatId from list_chats to target one chat unambiguously; otherwise identify it by topic (group chats) or the other person's display name (1:1 chats), which may be ambiguous. Use list_chats first if unsure.",
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
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof GetChatMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('limit', input.limit);

    this.logger.log({ userProfileId, limit: input.limit }, 'Getting chat messages');

    const { chatId, chatTopic } = await this.resolveChat(userProfileId, input, context);
    span?.setAttribute('resolved_chat_id', chatId);

    const messages = await this.chatService.getChatMessages(userProfileId, chatId, input.limit, {
      excludeSystemMessages: !input.includeSystemMessages,
    });

    span?.setAttribute('result_count', messages.length);

    return {
      chatId,
      chatTopic,
      messages: messages.map((m) => this.mapMessage(m, input)),
    };
  }

  // Prefer the exact chatId (topic is then unknown → null); otherwise resolve by
  // topic/member name, which also yields the topic for the response.
  private async resolveChat(
    userProfileId: string,
    input: z.infer<typeof GetChatMessagesInputSchema>,
    context: Context,
  ): Promise<{ chatId: string; chatTopic: string | null }> {
    if (input.chatId) {
      return { chatId: input.chatId, chatTopic: null };
    }
    if (input.chatIdentifier) {
      const chat = await this.chatService.resolveChatByNameOrMember(
        userProfileId,
        input.chatIdentifier,
        context,
      );
      return { chatId: chat.id, chatTopic: chat.topic ?? null };
    }
    throw new BadRequestException(
      'Provide either chatId (from list_chats) or chatIdentifier (topic or member name).',
    );
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
