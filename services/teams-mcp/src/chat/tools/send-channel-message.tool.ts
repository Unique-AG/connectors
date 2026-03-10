import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const SendChannelMessageInputSchema = z.object({
  teamName: z.string().describe('Display name of the team (case-insensitive)'),
  channelName: z.string().describe('Display name of the channel (case-insensitive)'),
  message: z.string().describe('Plain text message content to send'),
});

const SendChannelMessageOutputSchema = z.object({
  success: z.boolean(),
  messageId: z.string(),
  teamId: z.string(),
  channelId: z.string(),
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
      'Send a plain text message to a Microsoft Teams channel. Resolves team and channel by display name. Use list_teams and list_channels to discover available teams and channels.',
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
        'Use list_teams and list_channels first if you do not know the exact team or channel name.',
    },
  })
  @Span()
  public async sendChannelMessage(
    input: z.infer<typeof SendChannelMessageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SendChannelMessageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_name', input.teamName);
    span?.setAttribute('channel_name', input.channelName);
    span?.setAttribute('message_length', input.message.length);

    this.logger.log(
      { userProfileId, teamName: input.teamName, channelName: input.channelName },
      'Sending channel message',
    );

    return this.resolveAndSend(userProfileId, input.teamName, input.channelName, input.message);
  }

  private async resolveAndSend(
    userProfileId: string,
    teamName: string,
    channelName: string,
    message: string,
  ): Promise<z.output<typeof SendChannelMessageOutputSchema>> {
    const team = await this.channelService.resolveTeamByName(userProfileId, teamName);
    const channel = await this.channelService.resolveChannelByName(
      userProfileId,
      team.id,
      channelName,
      teamName,
    );
    const result = await this.channelService.sendChannelMessage(
      userProfileId,
      team.id,
      channel.id,
      message,
    );
    return {
      success: true,
      messageId: result.id,
      teamId: team.id,
      channelId: channel.id,
      webUrl: result.webUrl,
    };
  }
}
