import { ConflictException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MsChannel, MsChannelSchema, MsTeam, MsTeamSchema } from './chat.dtos';

@Injectable()
export class ChannelService {
  private readonly logger = new Logger(ChannelService.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
  ) {}

  @Span()
  public async listTeams(userProfileId: string): Promise<MsTeam[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Fetching joined teams from Microsoft Graph');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api('/me/joinedTeams').select('id,displayName,description').get();

    const teams = z.array(MsTeamSchema).parse(response.value);

    span?.setAttribute('result_count', teams.length);
    this.logger.debug({ userProfileId, count: teams.length }, 'Retrieved joined teams');

    return teams;
  }

  @Span()
  public async listChannels(userProfileId: string, teamId: string): Promise<MsChannel[]> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);

    this.logger.debug({ userProfileId, teamId }, 'Fetching channels from Microsoft Graph');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api(`/teams/${teamId}/channels`)
      .select('id,displayName,description')
      .get();

    const channels = z.array(MsChannelSchema).parse(response.value);

    span?.setAttribute('result_count', channels.length);
    this.logger.debug({ userProfileId, teamId, count: channels.length }, 'Retrieved team channels');

    return channels;
  }

  @Span()
  public async resolveTeamByName(userProfileId: string, teamName: string): Promise<MsTeam> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Resolving team by display name');

    const teams = await this.listTeams(userProfileId);

    // NOTE: case-insensitive match to avoid user friction when exact casing is unknown
    const lowerName = teamName.toLowerCase();
    const matches = teams.filter((t) => t.displayName.toLowerCase() === lowerName);

    if (matches.length === 0) {
      span?.addEvent('team not found');
      throw new NotFoundException(`Team "${teamName}" not found`);
    }

    // Multiple teams can share a display name; refuse to silently pick one and
    // risk acting on the wrong team.
    if (matches.length > 1) {
      span?.addEvent('ambiguous team name', { matchCount: matches.length });
      throw new ConflictException(
        `Team name "${teamName}" matches multiple teams (${matches.length}). Please be more specific.`,
      );
    }

    const [team] = matches as [MsTeam];
    span?.setAttribute('resolved_team_id', team.id);
    return team;
  }

  @Span()
  public async resolveChannelByName(
    userProfileId: string,
    teamId: string,
    channelName: string,
    teamName: string,
  ): Promise<MsChannel> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);

    this.logger.debug({ userProfileId, teamId }, 'Resolving channel by display name');

    const channels = await this.listChannels(userProfileId, teamId);

    // NOTE: case-insensitive match to avoid user friction when exact casing is unknown
    const lowerName = channelName.toLowerCase();
    const matches = channels.filter((c) => c.displayName.toLowerCase() === lowerName);

    if (matches.length === 0) {
      span?.addEvent('channel not found');
      throw new NotFoundException(`Channel "${channelName}" not found in team "${teamName}"`);
    }

    if (matches.length > 1) {
      span?.addEvent('ambiguous channel name', { matchCount: matches.length });
      throw new ConflictException(
        `Channel name "${channelName}" matches multiple channels in team "${teamName}" (${matches.length}). Please be more specific.`,
      );
    }

    const [channel] = matches as [MsChannel];
    span?.setAttribute('resolved_channel_id', channel.id);
    return channel;
  }

  @Span()
  public async sendChannelMessage(
    userProfileId: string,
    teamId: string,
    channelId: string,
    message: string,
  ): Promise<{ id: string; webUrl?: string }> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('team_id', teamId);
    span?.setAttribute('channel_id', channelId);
    span?.setAttribute('message_length', message.length);

    this.logger.debug({ userProfileId, teamId, channelId }, 'Sending message to channel');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api(`/teams/${teamId}/channels/${channelId}/messages`).post({
      body: {
        contentType: 'text',
        content: message,
      },
    });

    const result = z.object({ id: z.string(), webUrl: z.string().optional() }).parse(response);

    span?.setAttribute('message_id', result.id);
    this.logger.log(
      { userProfileId, teamId, channelId, messageId: result.id },
      'Message sent to channel',
    );

    return result;
  }
}
