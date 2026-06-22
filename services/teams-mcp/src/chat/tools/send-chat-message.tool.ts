import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { BadRequestException, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChatService } from '../chat.service';

const SendChatMessageInputSchema = z
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
    message: z.string().describe('Plain text message content to send'),
  })
  .refine((d) => d.chatId !== undefined || d.chatIdentifier !== undefined, {
    message: 'Provide either chatId (from list_chats) or chatIdentifier (topic or member name).',
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
      "Send a plain text message to a Microsoft Teams chat (1:1 or group). Prefer passing the chatId from list_chats to target one chat unambiguously; otherwise identify the chat by its topic or the other person's display name (which may be ambiguous). Use list_chats first to discover chats and their ids.",
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
        'Use list_chats first to get the chatId; pass it instead of a name when several chats share a topic or member.',
    },
  })
  @Span()
  public async sendChatMessage(
    input: z.infer<typeof SendChatMessageInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SendChatMessageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('message_length', input.message.length);

    this.logger.log({ userProfileId }, 'Sending chat message');

    const chatId = await this.resolveChatId(userProfileId, input, context);
    const result = await this.chatService.sendChatMessage(userProfileId, chatId, input.message);
    return { messageId: result.id, chatId };
  }

  // Prefer the exact chatId; fall back to resolving by topic/member name.
  private async resolveChatId(
    userProfileId: string,
    input: z.infer<typeof SendChatMessageInputSchema>,
    context: Context,
  ): Promise<string> {
    if (input.chatId) {
      return input.chatId;
    }
    if (input.chatIdentifier) {
      const chat = await this.chatService.resolveChatByNameOrMember(
        userProfileId,
        input.chatIdentifier,
        context,
      );
      return chat.id;
    }
    throw new BadRequestException(
      'Provide either chatId (from list_chats) or chatIdentifier (topic or member name).',
    );
  }
}
