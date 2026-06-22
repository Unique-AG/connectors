import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { BadRequestException, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';
import { MsChatMessage } from '../chat.dtos';
import { ChatService } from '../chat.service';
import { normalizeContent } from '../utils/normalize-content';

const GetChannelMessagesInputSchema = z
  .object({
    teamId: z
      .string()
      .optional()
      .describe(
        'Exact team id from list_teams/list_channels. Provide teamId + channelId (preferred, unambiguous) or teamName + channelName.',
      ),
    channelId: z
      .string()
      .optional()
      .describe('Exact channel id from list_channels. Use together with teamId.'),
    teamName: z
      .string()
      .optional()
      .describe(
        'Display name of the team (case-insensitive). Fallback when you do not have the ids; may match multiple teams.',
      ),
    channelName: z
      .string()
      .optional()
      .describe(
        'Display name of the channel (case-insensitive). Fallback used with teamName; may match multiple channels.',
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
  .refine((d) => (d.teamId && d.channelId) || (d.teamName && d.channelName), {
    message: 'Provide either teamId + channelId (from list_channels) or teamName + channelName.',
  });

const GetChannelMessagesOutputSchema = z.object({
  teamId: z.string(),
  channelId: z.string(),
  // Null when addressed by id (display names were not resolved).
  teamName: z.string().nullable(),
  channelName: z.string().nullable(),
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
      'Retrieves recent messages from a Microsoft Teams channel. Prefer passing teamId + channelId from list_teams/list_channels to target one channel unambiguously; otherwise resolve by teamName + channelName (which may be ambiguous). Use `list_teams` and `list_channels` first to discover teams, channels, and their ids.',
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
  @Span()
  public async getChannelMessages(
    input: z.infer<typeof GetChannelMessagesInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof GetChannelMessagesOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('limit', input.limit);

    this.logger.log({ userProfileId, limit: input.limit }, 'Getting channel messages');

    const { teamId, channelId, teamName, channelName } = await this.resolveTarget(
      userProfileId,
      input,
      context,
    );
    span?.setAttribute('resolved_team_id', teamId);
    span?.setAttribute('resolved_channel_id', channelId);

    const messages = await this.chatService.getChannelMessages(
      userProfileId,
      teamId,
      channelId,
      input.limit,
      { excludeSystemMessages: !input.includeSystemMessages },
    );

    span?.setAttribute('result_count', messages.length);

    return {
      teamId,
      channelId,
      teamName,
      channelName,
      messages: messages.map((m) => this.mapMessage(m, input)),
    };
  }

  // Prefer the exact teamId + channelId (display names then unknown → null);
  // otherwise resolve both by name, which also yields the names for the response.
  private async resolveTarget(
    userProfileId: string,
    input: z.infer<typeof GetChannelMessagesInputSchema>,
    context: Context,
  ): Promise<{
    teamId: string;
    channelId: string;
    teamName: string | null;
    channelName: string | null;
  }> {
    if (input.teamId && input.channelId) {
      return {
        teamId: input.teamId,
        channelId: input.channelId,
        teamName: null,
        channelName: null,
      };
    }
    if (input.teamName && input.channelName) {
      const team = await this.channelService.resolveTeamByName(
        userProfileId,
        input.teamName,
        context,
      );
      const channel = await this.channelService.resolveChannelByName(
        userProfileId,
        team.id,
        input.channelName,
        input.teamName,
        context,
      );
      return {
        teamId: team.id,
        channelId: channel.id,
        teamName: team.displayName,
        channelName: channel.displayName,
      };
    }
    throw new BadRequestException(
      'Provide either teamId + channelId (from list_channels) or teamName + channelName.',
    );
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

    if (input.detail === 'full') {
      msg.contentType = m.contentType;
    }

    return msg;
  }
}
