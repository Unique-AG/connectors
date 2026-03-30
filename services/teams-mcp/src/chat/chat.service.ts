import { ConflictException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MsChat, MsChatMessage, MsChatMessageSchema, MsChatSchema } from './chat.dtos';

@Injectable()
export class ChatService {
  private readonly logger = new Logger(ChatService.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
  ) {}

  @Span()
  public async listChats(userProfileId: string, limit = 50): Promise<MsChat[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Fetching chats from Microsoft Graph');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api('/me/chats')
      .expand('members')
      .top(limit)
      .select('id,chatType,topic,members')
      .get();

    const chats = z.array(MsChatSchema).parse(response.value);

    span?.setAttribute('result_count', chats.length);
    this.logger.debug({ userProfileId, count: chats.length }, 'Retrieved chats');

    return chats;
  }

  @Span()
  public async getChatMessages(
    userProfileId: string,
    chatId: string,
    limit: number,
    orderBy = 'createdDateTime desc',
  ): Promise<MsChatMessage[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('limit', limit);

    this.logger.debug(
      { userProfileId, chatId, limit },
      'Fetching chat messages from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/chats/${chatId}/messages`)
      .top(limit)
      .orderby(orderBy)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    const messages = z.array(MsChatMessageSchema).parse(response.value);

    span?.setAttribute('result_count', messages.length);
    this.logger.debug({ userProfileId, chatId, count: messages.length }, 'Retrieved chat messages');

    return messages;
  }

  @Span()
  public async resolveChatByNameOrMember(
    userProfileId: string,
    identifier: string,
  ): Promise<MsChat> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('identifier', identifier);

    this.logger.debug({ userProfileId, identifier }, 'Resolving chat by topic or member name');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const [chats, me] = await Promise.all([
      this.listChats(userProfileId),
      client.api('/me').select('id').get() as Promise<{ id: string }>,
    ]);
    const currentUserId = me.id;
    const lowerIdentifier = identifier.toLowerCase();

    // NOTE: exact case-insensitive match — topic first, then member display name for 1:1 chats.
    // Group chats without a topic are only matchable by topic; oneOnOne chats fall back to member name.
    // For oneOnOne chats, the current user is excluded from member matching to avoid every 1:1 chat
    // matching when the user searches for their own name.
    const matches = chats.filter((c) => {
      if (c.topic?.toLowerCase() === lowerIdentifier) {
        return true;
      }
      if (c.chatType === 'oneOnOne') {
        return c.members.some(
          (m) => m.userId !== currentUserId && m.displayName?.toLowerCase() === lowerIdentifier,
        );
      }
      return false;
    });

    if (matches.length === 0) {
      span?.addEvent('chat not found', { identifier });
      throw new NotFoundException(`Chat "${identifier}" not found`);
    }

    // TODO: replace with context.elicitInput() once exposed on Context interface
    // in mcp-server-module. Present a picker with chat type, topic/member name,
    // and last message timestamp so the user can select the intended chat.
    if (matches.length > 1) {
      const matchDescriptions = matches
        .map((c) => c.topic ?? c.members.map((m) => m.displayName).join(', '))
        .join('; ');
      span?.addEvent('ambiguous chat identifier', { identifier, matchCount: matches.length });
      throw new ConflictException(
        `Identifier "${identifier}" matches multiple chats: ${matchDescriptions}. Please be more specific.`,
      );
    }

    // matches.length === 1 is guaranteed by the checks above
    const [chat] = matches as [MsChat];
    span?.setAttribute('resolved_chat_id', chat.id);
    return chat;
  }

  @Span()
  public async getChannelMessages(
    userProfileId: string,
    teamId: string,
    channelId: string,
    limit: number,
    orderBy = 'createdDateTime desc',
  ): Promise<MsChatMessage[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);
    span?.setAttribute('channel_id', channelId);
    span?.setAttribute('limit', limit);

    this.logger.debug(
      { userProfileId, teamId, channelId, limit },
      'Fetching channel messages from Microsoft Graph',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/teams/${teamId}/channels/${channelId}/messages`)
      .top(limit)
      .orderby(orderBy)
      .select('id,createdDateTime,from,body,attachments,messageType')
      .get();

    const messages = z.array(MsChatMessageSchema).parse(response.value);

    span?.setAttribute('result_count', messages.length);
    this.logger.debug(
      { userProfileId, teamId, channelId, count: messages.length },
      'Retrieved channel messages',
    );

    return messages;
  }

  @Span()
  public async sendChatMessage(
    userProfileId: string,
    chatId: string,
    message: string,
  ): Promise<{ id: string }> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('chat_id', chatId);
    span?.setAttribute('message_length', message.length);

    this.logger.debug({ userProfileId, chatId }, 'Sending message to chat');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api(`/chats/${chatId}/messages`).post({
      body: {
        contentType: 'text',
        content: message,
      },
    });

    const result = z.object({ id: z.string() }).parse(response);

    span?.setAttribute('message_id', result.id);
    this.logger.log({ userProfileId, chatId, messageId: result.id }, 'Message sent to chat');

    return result;
  }
}
