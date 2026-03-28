import { Effect, ServiceMap } from 'effect';
import type {
  InsufficientPermissionsError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../errors/errors.js';
import type { ODataPageType, ODataParams } from '../schemas/odata.schema.js';
import type { Channel, ChatMessage, Team } from './team.schema.js';

export class TeamsService extends ServiceMap.Service<
  TeamsService,
  {
    readonly listTeams: (
      params?: ODataParams<Team>,
    ) => Effect.Effect<ODataPageType<Team>, RateLimitedError>;

    readonly getTeam: (
      teamId: string,
    ) => Effect.Effect<Team, ResourceNotFoundError | RateLimitedError>;

    readonly listChannels: (
      teamId: string,
    ) => Effect.Effect<ODataPageType<Channel>, ResourceNotFoundError | RateLimitedError>;

    readonly listMessages: (
      teamId: string,
      channelId: string,
      params?: ODataParams<ChatMessage>,
    ) => Effect.Effect<ODataPageType<ChatMessage>, ResourceNotFoundError | RateLimitedError>;

    readonly sendMessage: (
      teamId: string,
      channelId: string,
      content: string,
      contentType?: 'text' | 'html',
    ) => Effect.Effect<
      ChatMessage,
      ResourceNotFoundError | InsufficientPermissionsError | RateLimitedError
    >;

    readonly replyToMessage: (
      teamId: string,
      channelId: string,
      messageId: string,
      content: string,
    ) => Effect.Effect<ChatMessage, ResourceNotFoundError | RateLimitedError>;
  }
>()('MsGraph/Teams/TeamsService') {}
