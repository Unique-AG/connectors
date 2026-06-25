import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChatService } from '../chat.service';

const SendChatMessageInputSchema = z.object({
  chatId: z
    .string()
    .describe('Exact chat id from list_chats or search_messages. Use list_chats first to find it.'),
  message: z.string().describe('Plain text message content to send'),
});

const SendChatMessageOutputSchema = z.object({
  messageId: z.string(),
  chatId: z.string(),
});

@Injectable()
export class SendChatMessageTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  @Tool({
    name: 'send_chat_message',
    title: 'Send Chat Message',
    description:
      'Send a plain text message to a Microsoft Teams chat (1:1 or group), identified by its chatId. Call list_chats first to find the chatId (it also returns topic/members/dates so you can pick the right chat).',
    parameters: SendChatMessageInputSchema,
    outputSchema: SendChatMessageOutputSchema,
    annotations: {
      title: 'Send Chat Message',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'send',
      'unique.app/system-prompt': 'Call list_chats first to get the chatId, then send by chatId.',
    },
  })
  @Span()
  public async sendChatMessage(
    input: z.infer<typeof SendChatMessageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SendChatMessageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const { chatId, message } = input;
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('message_length', message.length);

    this.logger.log({ userProfileId }, 'Sending chat message');

    const result = await this.chatService.sendChatMessage(userProfileId, chatId, message);
    return { messageId: result.id, chatId };
  }
}
