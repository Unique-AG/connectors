import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { MsChat } from '../chat.dtos';
import { ChatService } from '../chat.service';

const LIMIT = 50;

const ListChatsInputSchema = z.object({
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(LIMIT)
    .describe('Maximum number of chats to return. Default: 50'),
  includeMemberEmails: z
    .boolean()
    .default(false)
    .describe(
      'Include member email addresses. Useful for disambiguation when two members share a display name. Default: false',
    ),
});

const ListChatsOutputSchema = z.object({
  chats: z.array(
    z.object({
      chatType: z.string(),
      topic: z.string().nullable(),
      members: z
        .array(
          z.object({
            displayName: z.string().nullable(),
            email: z.string().nullable().optional(),
          }),
        )
        .optional(),
    }),
  ),
  truncated: z.boolean(),
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
    input: z.infer<typeof ListChatsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListChatsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Listing chats for user');

    const effectiveLimit = input.limit ?? LIMIT;
    const chats = await this.chatService.listChats(userProfileId, effectiveLimit);

    span?.setAttribute('result_count', chats.length);

    return {
      chats: chats.map((c) => this.mapChat(c, input.includeMemberEmails)),
      truncated: chats.length === effectiveLimit,
    };
  }

  private mapChat(
    c: MsChat,
    includeMemberEmails: boolean,
  ): z.output<typeof ListChatsOutputSchema>['chats'][number] {
    const chat: {
      chatType: string;
      topic: string | null;
      members?: { displayName: string | null; email?: string | null }[];
    } = {
      chatType: c.chatType,
      topic: c.topic ?? null,
    };

    // Only include members for chats without a topic (1:1 chats need member names as their identifier)
    if (!c.topic) {
      chat.members = c.members.map((m) => {
        const member: { displayName: string | null; email?: string | null } = {
          displayName: m.displayName ?? null,
        };
        if (includeMemberEmails) {
          member.email = m.email ?? null;
        }
        return member;
      });
    }

    return chat;
  }
}
