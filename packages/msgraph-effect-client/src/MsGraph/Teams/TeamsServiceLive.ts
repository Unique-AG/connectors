import { Effect, Layer, Match } from 'effect';
import type { ApplicationAuth, DelegatedAuth } from '../Auth/MsGraphAuth';
import { toNotFoundOrRateLimit, toRateLimit } from '../Errors/errorNarrowers';
import type { MsGraphError } from '../Errors/errors';
import { InsufficientPermissionsError } from '../Errors/errors';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import type { ChatMessage, Team } from '../Schemas/Team';
import { ChannelSchema, ChatMessageSchema, TeamSchema } from '../Schemas/Team';
import { TeamsService } from './TeamsService';

const TeamPageSchema = ODataPage(TeamSchema);
const ChannelPageSchema = ODataPage(ChannelSchema);
const ChatMessagePageSchema = ODataPage(ChatMessageSchema);

const narrowToRateLimitNotFoundOrInsufficient = Match.type<MsGraphError>().pipe(
  Match.tag('RateLimitedError', (e) => e),
  Match.tag('ResourceNotFound', (e) => e),
  Match.tag('InsufficientPermissions', (e) => e),
  Match.orElse(
    (e) =>
      new InsufficientPermissionsError({
        requiredScope: e._tag,
        grantedScopes: [],
      }),
  ),
);

export const TeamsServiceLive = Layer.effect(
  TeamsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient;

    const listTeams = Effect.fn('TeamsService.listTeams')(
      function* (params?: ODataParams<Team>) {
        const qs = params ? buildQueryString<Team>(params as ODataParams<Team>) : '';
        return yield* http
          .get(`/me/joinedTeams${qs}`, TeamPageSchema)
          .pipe(Effect.mapError(toRateLimit('/me/joinedTeams')));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'listTeams' }),
    );

    const getTeam = Effect.fn('TeamsService.getTeam')(
      function* (teamId: string) {
        const path = `/teams/${teamId}`;
        return yield* http.get(path, TeamSchema).pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'getTeam' }),
    );

    const listChannels = Effect.fn('TeamsService.listChannels')(
      function* (teamId: string) {
        const path = `/teams/${teamId}/channels`;
        return yield* http
          .get(path, ChannelPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'listChannels' }),
    );

    const listMessages = Effect.fn('TeamsService.listMessages')(
      function* (teamId: string, channelId: string, params?: ODataParams<ChatMessage>) {
        const basePath = `/teams/${teamId}/channels/${channelId}/messages`;
        const qs = params ? buildQueryString<ChatMessage>(params as ODataParams<ChatMessage>) : '';
        return yield* http
          .get(`${basePath}${qs}`, ChatMessagePageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(basePath)));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'listMessages' }),
    );

    const sendMessage = Effect.fn('TeamsService.sendMessage')(
      function* (
        teamId: string,
        channelId: string,
        content: string,
        contentType: 'text' | 'html' = 'text',
      ) {
        const path = `/teams/${teamId}/channels/${channelId}/messages`;
        return yield* http
          .post(path, { body: { contentType, content } }, ChatMessageSchema)
          .pipe(Effect.mapError(narrowToRateLimitNotFoundOrInsufficient));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'sendMessage' }),
    );

    const replyToMessage = Effect.fn('TeamsService.replyToMessage')(
      function* (teamId: string, channelId: string, messageId: string, content: string) {
        const path = `/teams/${teamId}/channels/${channelId}/messages/${messageId}/replies`;
        return yield* http
          .post(path, { body: { contentType: 'text', content } }, ChatMessageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'TeamsService', method: 'replyToMessage' }),
    );

    return TeamsService.of({
      listTeams,
      getTeam,
      listChannels,
      listMessages,
      sendMessage,
      replyToMessage,
    });
  }).pipe(Effect.withSpan('TeamsServiceLive.initialize')),
) as Layer.Layer<TeamsService, never, MsGraphHttpClient | ApplicationAuth | DelegatedAuth>;
