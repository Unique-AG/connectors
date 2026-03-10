import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { MsChat } from '../chat.dtos';
import { ChatService } from '../chat.service';

const ListChatsInputSchema = z.object({});

const ListChatsOutputSchema = z.object({
  chats: z.array(
    z.object({
      id: z.string(),
      chatType: z.string(),
      topic: z.string().nullable(),
      members: z.array(
        z.object({
          displayName: z.string().nullable(),
          email: z.string().nullable(),
        }),
      ),
    }),
  ),
  count: z.number(),
});

@Injectable()
export class ListChatsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  @Tool({
    name: 'list_chats',
    title: 'List My Chats',
    description:
      "List the current user's Microsoft Teams chats (1:1, group, and meeting chats). Returns up to 50 most recent chats. Use the topic or a member's display name as chatIdentifier in get_chat_messages or send_chat_message.",
    parameters: ListChatsInputSchema,
    outputSchema: ListChatsOutputSchema,
    annotations: {
      title: 'List My Chats',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'message-circle',
    },
  })
  @Span()
  public async listChats(
    _input: z.infer<typeof ListChatsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListChatsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Listing chats for user');

    const chats = await this.chatService.listChats(userProfileId);

    span?.setAttribute('result_count', chats.length);

    return { chats: chats.map((c) => this.mapChat(c)), count: chats.length };
  }

  private mapChat(c: MsChat): z.output<typeof ListChatsOutputSchema>['chats'][number] {
    return {
      id: c.id,
      chatType: c.chatType,
      topic: c.topic ?? null,
      members: c.members.map((m) => ({
        displayName: m.displayName ?? null,
        email: m.email ?? null,
      })),
    };
  }
}
