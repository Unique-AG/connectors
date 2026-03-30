import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChatService } from '../chat.service';

const SendChatMessageInputSchema = z.object({
  chatIdentifier: z.string().describe('Chat topic or member display name (case-insensitive)'),
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
      "Send a plain text message to a Microsoft Teams chat (1:1 or group). Identify the chat by its topic or the other person's display name. Use list_chats first to discover available chats.",
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
      'unique.app/system-prompt':
        'Use list_chats first if you do not know the exact chat identifier.',
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

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_identifier', input.chatIdentifier);
    span?.setAttribute('message_length', input.message.length);

    this.logger.log(
      { userProfileId, chatIdentifier: input.chatIdentifier },
      'Sending chat message',
    );

    return this.resolveAndSend(userProfileId, input.chatIdentifier, input.message);
  }

  private async resolveAndSend(
    userProfileId: string,
    chatIdentifier: string,
    message: string,
  ): Promise<z.output<typeof SendChatMessageOutputSchema>> {
    const chat = await this.chatService.resolveChatByNameOrMember(userProfileId, chatIdentifier);
    const result = await this.chatService.sendChatMessage(userProfileId, chat.id, message);
    return { messageId: result.id, chatId: chat.id };
  }
}
