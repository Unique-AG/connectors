import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { ChannelService } from '../channel.service';

const ListTeamsInputSchema = z.object({
  includeDescriptions: z
    .boolean()
    .default(false)
    .describe(
      'Include team descriptions. Useful when multiple teams have similar names and disambiguation is needed. Default: false',
    ),
});

const ListTeamsOutputSchema = z.object({
  teams: z.array(
    z.object({
      teamId: z.string(),
      displayName: z.string(),
      description: z.string().optional(),
      isArchived: z.boolean().nullable(),
    }),
  ),
});

@Injectable()
export class ListTeamsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly channelService: ChannelService,
  ) {}

  @Tool({
    name: 'list_teams',
    title: 'List My Teams',
    description:
      'List all Microsoft Teams the current user is a member of. Each team includes its teamId and an isArchived flag (archived teams are read-only) to distinguish teams that share a display name. Pass the teamId to list_channels, send_channel_message, or get_channel_messages to target a specific team unambiguously.',
    parameters: ListTeamsInputSchema,
    outputSchema: ListTeamsOutputSchema,
    annotations: {
      title: 'List My Teams',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'users',
    },
  })
  @Span()
  public async listTeams(
    input: z.infer<typeof ListTeamsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListTeamsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Listing teams for user');

    const teams = await this.channelService.listTeams(userProfileId);

    span?.setAttribute('result_count', teams.length);

    return {
      teams: teams.map((t) => {
        const team: {
          teamId: string;
          displayName: string;
          description?: string;
          isArchived: boolean | null;
        } = {
          teamId: t.id,
          displayName: t.displayName,
          isArchived: t.isArchived ?? null,
        };
        if (input.includeDescriptions && t.description) {
          team.description = t.description;
        }
        return team;
      }),
    };
  }
}
