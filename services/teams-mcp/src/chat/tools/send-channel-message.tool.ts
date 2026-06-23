import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { BadRequestException, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const SendChannelMessageInputSchema = z
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
    message: z.string().describe('Plain text message content to send'),
    includeWebUrl: z
      .boolean()
      .default(false)
      .describe('Include the Teams web URL of the sent message. Default: false'),
  })
  .refine(
    (d) => {
      // When any id is supplied, require the full teamId + channelId pair. A
      // partial id (only one) must not pass via the name pair and silently
      // resolve a different channel than the id implied.
      if (d.teamId !== undefined || d.channelId !== undefined) {
        return d.teamId !== undefined && d.channelId !== undefined;
      }
      return d.teamName !== undefined && d.channelName !== undefined;
    },
    {
      message:
        'Provide a complete teamId + channelId (from list_channels) or teamName + channelName. A partial id is not allowed.',
    },
  );

const SendChannelMessageOutputSchema = z.object({
  messageId: z.string(),
  webUrl: z.string().optional(),
});

@Injectable()
export class SendChannelMessageTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly channelService: ChannelService,
  ) {}

  @Tool({
    name: 'send_channel_message',
    title: 'Send Channel Message',
    description:
      'Send a plain text message to a Microsoft Teams channel. Prefer passing teamId + channelId from list_teams/list_channels to target one channel unambiguously; otherwise resolve by teamName + channelName (which may be ambiguous). Use list_teams and list_channels to discover teams, channels, and their ids.',
    parameters: SendChannelMessageInputSchema,
    outputSchema: SendChannelMessageOutputSchema,
    annotations: {
      title: 'Send Channel Message',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'send',
      'unique.app/system-prompt':
        'Use list_teams and list_channels first to get teamId + channelId; pass them instead of names when several teams or channels share a name.',
    },
  })
  @Span()
  public async sendChannelMessage(
    input: z.infer<typeof SendChannelMessageInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SendChannelMessageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('message_length', input.message.length);

    this.logger.log({ userProfileId }, 'Sending channel message');

    const { teamId, channelId } = await this.resolveTarget(userProfileId, input, context);
    const result = await this.channelService.sendChannelMessage(
      userProfileId,
      teamId,
      channelId,
      input.message,
    );
    return {
      messageId: result.id,
      ...(input.includeWebUrl && result.webUrl ? { webUrl: result.webUrl } : {}),
    };
  }

  // Prefer the exact teamId + channelId; fall back to resolving both by name.
  private async resolveTarget(
    userProfileId: string,
    input: z.infer<typeof SendChannelMessageInputSchema>,
    context: Context,
  ): Promise<{ teamId: string; channelId: string }> {
    if (input.teamId && input.channelId) {
      return { teamId: input.teamId, channelId: input.channelId };
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
      return { teamId: team.id, channelId: channel.id };
    }
    throw new BadRequestException(
      'Provide either teamId + channelId (from list_channels) or teamName + channelName.',
    );
  }
}
