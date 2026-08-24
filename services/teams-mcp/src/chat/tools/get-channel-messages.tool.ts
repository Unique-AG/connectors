import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { AttributeUpstreamErrors } from '../../utils/attribute-upstream-errors.decorator';
import { MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { normalizeContent } from '../utils/normalize-content';

export const GetChannelMessagesInputSchema = z.object({
  teamId: z.string().describe('Exact team id from list_teams. Use list_teams to find it.'),
  channelId: z
    .string()
    .describe(
      'Exact channel id from list_channels. Use list_channels (with the teamId) to find it.',
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

const GetChannelMessagesOutputSchema = z.object({
  teamId: z.string(),
  channelId: z.string(),
  messages: z.array(
    z.object({
      id: z.string(),
      createdDateTime: z.string(),
      senderDisplayName: z.string().nullable(),
      content: z.string(),
    }),
  ),
});

@Injectable()
export class GetChannelMessagesTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  @Tool({
    name: 'get_channel_messages',
    title: 'Get Channel Messages',
    description:
      'Retrieves recent messages from a Microsoft Teams channel, identified by teamId + channelId. Call list_teams then list_channels (with that teamId) first to find the ids. Message bodies are always normalized plain text, never Teams HTML, and timestamps are the ISO 8601 values Graph returns. System messages (member added, call ended) are excluded unless includeSystemMessages is set.',
    parameters: GetChannelMessagesInputSchema,
    outputSchema: GetChannelMessagesOutputSchema,
    annotations: {
      title: 'Get Channel Messages',
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
  public async getChannelMessages(
    input: z.infer<typeof GetChannelMessagesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof GetChannelMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', input.teamId);
    span?.setAttribute('channel_id', input.channelId);
    span?.setAttribute('limit', input.limit);

    this.logger.log({ userProfileId, limit: input.limit }, 'Getting channel messages');

    const messages = await this.chatService.getChannelMessages(
      userProfileId,
      input.teamId,
      input.channelId,
      input.limit,
      { excludeSystemMessages: !input.includeSystemMessages },
    );

    span?.setAttribute('result_count', messages.length);

    return {
      teamId: input.teamId,
      channelId: input.channelId,
      messages: messages.map((m) => this.mapMessage(m)),
    };
  }

  private mapMessage(
    m: MsChatMessage,
  ): z.output<typeof GetChannelMessagesOutputSchema>['messages'][number] {
    return {
      id: m.id,
      createdDateTime: m.createdDateTime,
      senderDisplayName: m.senderDisplayName ?? null,
      content: normalizeContent(m.content, m.contentType, m.attachments, m.deletedDateTime),
    };
  }
}
