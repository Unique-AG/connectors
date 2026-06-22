import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { BadRequestException, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const ListChannelsInputSchema = z.object({
  teamId: z
    .string()
    .optional()
    .describe('Exact team id from list_teams. Preferred — unambiguous. Provide this or teamName.'),
  teamName: z
    .string()
    .optional()
    .describe(
      'Display name of the team (case-insensitive). Fallback when you do not have the teamId; may match multiple teams.',
    ),
  includeDescriptions: z
    .boolean()
    .default(false)
    .describe(
      'Include channel descriptions. Useful when multiple channels have similar names and disambiguation is needed. Default: false',
    ),
});

const ListChannelsOutputSchema = z.object({
  teamId: z.string(),
  // Null when the team was addressed by teamId (the display name was not resolved).
  teamName: z.string().nullable(),
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
      'List all channels in a Microsoft Teams team (addressed by teamId from list_teams, or by teamName). Each channel includes its channelId plus creation date and membership type (standard, private, or shared). Pass the teamId + channelId to send_channel_message or get_channel_messages to target a specific channel unambiguously.',
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
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListChannelsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Listing channels for team');

    // Prefer the exact teamId; fall back to resolving the team by display name.
    let teamId: string;
    let teamName: string | null;
    if (input.teamId) {
      teamId = input.teamId;
      teamName = null;
    } else if (input.teamName) {
      const team = await this.channelService.resolveTeamByName(
        userProfileId,
        input.teamName,
        context,
      );
      teamId = team.id;
      teamName = team.displayName;
    } else {
      throw new BadRequestException('Provide either teamId (from list_teams) or teamName.');
    }

    const channels = await this.channelService.listChannels(userProfileId, teamId);
    span?.setAttribute('resolved_team_id', teamId);
    span?.setAttribute('result_count', channels.length);

    return {
      teamId,
      teamName,
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
