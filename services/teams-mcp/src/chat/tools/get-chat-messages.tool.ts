import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { AttributeUpstreamErrors } from '../../utils/attribute-upstream-errors.decorator';
import { MessageOutputSchema } from '../chat.dtos';
import { ChatService } from '../chat.service';

export const GetChatMessagesInputSchema = z.object({
  chatId: z
    .string()
    .describe(
      'Opaque Microsoft Teams chat id (e.g. "19:...@thread.v2"). Do not invent, guess, or reconstruct this id; only copy an exact chatId returned by list_chats or search_messages. If you do not have one, call list_chats first.',
    ),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(20)
    .describe('Maximum number of messages to return (newest first)'),
  includeSystemMessages: z
    .boolean()
    .default(false)
    .describe(
      'System messages are event notifications (member added, call ended). Default false excludes them',
    ),
});

const GetChatMessagesOutputSchema = z.object({
  chatId: z.string(),
  messages: z.array(MessageOutputSchema),
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
      'Read the most recent messages in a Microsoft Teams chat. Take the chatId from list_chats or search_messages. ' +
      'Each message comes with its body, sender, timestamps, mentions, attachments and reactions. ' +
      'Message bodies are Teams HTML. ' +
      'Set includeSystemMessages to true to also see event notices, such as a member joining.',
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
  @AttributeUpstreamErrors()
  @Span()
  public async getChatMessages(
    input: z.infer<typeof GetChatMessagesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof GetChatMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', input.chatId);
    span?.setAttribute('limit', input.limit);

    this.logger.log({ userProfileId, limit: input.limit }, 'Getting chat messages');

    const messages = await this.chatService.getChatMessages(
      userProfileId,
      input.chatId,
      input.limit,
      {
        excludeSystemMessages: !input.includeSystemMessages,
      },
    );

    span?.setAttribute('result_count', messages.length);

    return {
      chatId: input.chatId,
      messages,
    };
  }
}
