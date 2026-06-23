import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const SendChannelMessageInputSchema = z.object({
  teamId: z.string().describe('Exact team id from list_teams. Use list_teams to find it.'),
  channelId: z
    .string()
    .describe(
      'Exact channel id from list_channels. Use list_channels (with the teamId) to find it.',
    ),
  message: z.string().describe('Plain text message content to send'),
  includeWebUrl: z
    .boolean()
    .default(false)
    .describe('Include the Teams web URL of the sent message. Default: false'),
});

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
      'Send a plain text message to a Microsoft Teams channel, identified by teamId + channelId. Call list_teams then list_channels (with that teamId) first to find the ids.',
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
        'Call list_teams then list_channels first to get teamId + channelId, then send by id.',
    },
  })
  @Span()
  public async sendChannelMessage(
    input: z.infer<typeof SendChannelMessageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SendChannelMessageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', input.teamId);
    span?.setAttribute('channel_id', input.channelId);
    span?.setAttribute('message_length', input.message.length);

    this.logger.log({ userProfileId }, 'Sending channel message');

    const result = await this.channelService.sendChannelMessage(
      userProfileId,
      input.teamId,
      input.channelId,
      input.message,
    );
    return {
      messageId: result.id,
      ...(input.includeWebUrl && result.webUrl ? { webUrl: result.webUrl } : {}),
    };
  }
}
