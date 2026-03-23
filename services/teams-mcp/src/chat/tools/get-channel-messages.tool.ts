import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';
import { MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { normalizeContent } from '../utils/normalize-content';

const GetChannelMessagesInputSchema = z.object({
  teamName: z.string().describe('Display name of the team (case-insensitive)'),
  channelName: z.string().describe('Display name of the channel (case-insensitive)'),
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
});

const GetChannelMessagesOutputSchema = z.object({
  teamName: z.string(),
  channelName: z.string(),
  messages: z.array(
    z.object({
      id: z.string(),
      createdDateTime: z.string().optional(),
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
    private readonly channelService: ChannelService,
    private readonly chatService: ChatService,
  ) {}

  @Tool({
    name: 'get_channel_messages',
    title: 'Get Channel Messages',
    description:
      'Retrieves recent messages from a Microsoft Teams channel. Use `list_teams` and `list_channels` first to discover available teams and channels.',
    parameters: GetChannelMessagesInputSchema,
    outputSchema: GetChannelMessagesOutputSchema,
    annotations: {
      title: 'Get Channel Messages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'message-square',
    },
  })
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
    span?.setAttribute('team_name', input.teamName);
    span?.setAttribute('channel_name', input.channelName);
    span?.setAttribute('limit', input.limit);

    this.logger.log(
      {
        userProfileId,
        teamName: input.teamName,
        channelName: input.channelName,
        limit: input.limit,
      },
      'Getting channel messages',
    );

    const team = await this.channelService.resolveTeamByName(userProfileId, input.teamName);

    // TODO: if channel resolution fails, could use context.elicitInput() to show
    // available channels as a picker rather than throwing NotFoundException.
    const channel = await this.channelService.resolveChannelByName(
      userProfileId,
      team.id,
      input.channelName,
      input.teamName,
    );

    const messages = await this.chatService.getChannelMessages(
      userProfileId,
      team.id,
      channel.id,
      input.limit,
    );

    span?.setAttribute('result_count', messages.length);

    const filtered = input.includeSystemMessages
      ? messages
      : messages.filter((m) => m.senderDisplayName !== undefined);

    return {
      teamName: team.displayName,
      channelName: channel.displayName,
      messages: filtered.map((m) => this.mapMessage(m, input)),
    };
  }

  private mapMessage(
    m: MsChatMessage,
    input: z.infer<typeof GetChannelMessagesInputSchema>,
  ): z.output<typeof GetChannelMessagesOutputSchema>['messages'][number] {
    const content =
      input.contentFormat === 'normalized'
        ? normalizeContent(m.content, m.contentType, m.attachments)
        : m.content;

    const msg: z.output<typeof GetChannelMessagesOutputSchema>['messages'][number] = {
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

    return msg;
  }
}
