import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { AttributeUpstreamErrors } from '../../utils/attribute-upstream-errors.decorator';
import { ChannelService } from '../channel.service';

const ListChannelsInputSchema = z.object({
  teamId: z.string().describe('Exact team id from list_teams. Use list_teams to find it.'),
  includeDescriptions: z
    .boolean()
    .default(false)
    .describe(
      'Include channel descriptions. Useful when multiple channels have similar names and disambiguation is needed. Default: false',
    ),
});

const ListChannelsOutputSchema = z.object({
  teamId: z.string(),
  channels: z.array(
    z.object({
      channelId: z.string(),
      displayName: z.string(),
      description: z.string().optional(),
      createdDateTime: z.string().nullable(),
      membershipType: z.string().nullable(),
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
      'List all channels in a Microsoft Teams team, identified by teamId (from list_teams). Each channel includes its channelId plus creation date and membership type (standard, private, or shared). Pass the teamId + channelId to send_channel_message or get_channel_messages.',
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
  @AttributeUpstreamErrors()
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
    span?.setAttribute('team_id', input.teamId);

    this.logger.log({ userProfileId }, 'Listing channels for team');

    const channels = await this.channelService.listChannels(userProfileId, input.teamId);
    span?.setAttribute('result_count', channels.length);

    return {
      teamId: input.teamId,
      channels: channels.map((c) => {
        const channel: {
          channelId: string;
          displayName: string;
          description?: string;
          createdDateTime: string | null;
          membershipType: string | null;
        } = {
          channelId: c.id,
          displayName: c.displayName,
          createdDateTime: c.createdDateTime ?? null,
          membershipType: c.membershipType ?? null,
        };
        if (input.includeDescriptions && c.description) {
          channel.description = c.description;
        }
        return channel;
      }),
    };
  }
}
