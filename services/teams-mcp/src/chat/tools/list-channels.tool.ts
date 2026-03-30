import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const ListChannelsInputSchema = z.object({
  teamName: z.string().describe('Display name of the team (case-insensitive)'),
  includeDescriptions: z
    .boolean()
    .default(false)
    .describe(
      'Include channel descriptions. Useful when multiple channels have similar names and disambiguation is needed. Default: false',
    ),
});

const ListChannelsOutputSchema = z.object({
  teamName: z.string(),
  channels: z.array(
    z.object({
      displayName: z.string(),
      description: z.string().optional(),
    }),
  ),
});

@Injectable()
export class ListChannelsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly channelService: ChannelService,
  ) {}

  @Tool({
    name: 'list_channels',
    title: 'List Team Channels',
    description:
      'List all channels in a Microsoft Teams team. Use this to discover channel names before calling send_channel_message.',
    parameters: ListChannelsInputSchema,
    outputSchema: ListChannelsOutputSchema,
    annotations: {
      title: 'List Team Channels',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'hash',
    },
  })
  @Span()
  public async listChannels(
    input: z.infer<typeof ListChannelsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListChannelsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_name', input.teamName);

    this.logger.log({ userProfileId, teamName: input.teamName }, 'Listing channels for team');

    const team = await this.channelService.resolveTeamByName(userProfileId, input.teamName);
    const channels = await this.channelService.listChannels(userProfileId, team.id);

    span?.setAttribute('result_count', channels.length);

    return {
      teamName: team.displayName,
      channels: channels.map((c) => {
        const channel: { displayName: string; description?: string } = {
          displayName: c.displayName,
        };
        if (input.includeDescriptions && c.description) {
          channel.description = c.description;
        }
        return channel;
      }),
    };
  }
}
