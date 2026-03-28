import { Effect, Layer, Match } from 'effect';
import type { ApplicationAuth } from '../Auth/MsGraphAuth';
import { toNotFoundOrRateLimit, toRateLimitOrInvalid } from '../Errors/errorNarrowers';
import type { MsGraphError } from '../Errors/errors';
import { RateLimitedError, ResourceNotFoundError } from '../Errors/errors';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { Group } from '../Schemas/Group';
import { GroupSchema } from '../Schemas/Group';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import { UserSchema } from '../Schemas/User';
import { GroupsService } from './GroupsService';

const GroupPageSchema = ODataPage(GroupSchema);
const UserPageSchema = ODataPage(UserSchema);

const GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0';

const narrowToRateLimitNotFoundOrInvalidRequest = Match.type<MsGraphError>().pipe(
  Match.tag('RateLimitedError', (e) => e),
  Match.tag('ResourceNotFound', (e) => e),
  Match.tag('InvalidRequest', (e) => e),
  Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource: 'groups' })),
);

export const GroupsServiceLive = Layer.effect(
  GroupsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient;

    const list = Effect.fn('GroupsService.list')(
      function* (params?: ODataParams<Group>) {
        const qs = params ? buildQueryString<Group>(params as ODataParams<Group>) : '';
        const path = `/groups${qs}`;
        return yield* http
          .get(path, GroupPageSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid('/groups')));
      },
      Effect.annotateLogs({ service: 'GroupsService', method: 'list' }),
    );

    const getById = Effect.fn('GroupsService.getById')(
      function* (groupId: string) {
        const path = `/groups/${groupId}`;
        return yield* http
          .get(path, GroupSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'GroupsService', method: 'getById' }),
    );

    const listMembers = Effect.fn('GroupsService.listMembers')(
      function* (groupId: string) {
        const path = `/groups/${groupId}/members`;
        return yield* http
          .get(path, UserPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'GroupsService', method: 'listMembers' }),
    );

    const addMember = Effect.fn('GroupsService.addMember')(
      function* (groupId: string, userId: string) {
        return yield* http
          .postVoid(`/groups/${groupId}/members/$ref`, {
            '@odata.id': `${GRAPH_BASE_URL}/directoryObjects/${userId}`,
          })
          .pipe(Effect.mapError(narrowToRateLimitNotFoundOrInvalidRequest));
      },
      Effect.annotateLogs({ service: 'GroupsService', method: 'addMember' }),
    );

    const removeMember = Effect.fn('GroupsService.removeMember')(
      function* (groupId: string, userId: string) {
        const path = `/groups/${groupId}/members/${userId}/$ref`;
        return yield* http.delete(path).pipe(
          Effect.mapError(
            Match.type<MsGraphError>().pipe(
              Match.tag('RateLimitedError', (e) => e),
              Match.tag('ResourceNotFound', (e) => e),
              Match.orElse(
                () => new ResourceNotFoundError({ resource: 'groupMember', id: userId }),
              ),
            ),
          ),
        );
      },
      Effect.annotateLogs({ service: 'GroupsService', method: 'removeMember' }),
    );

    return GroupsService.of({
      list,
      getById,
      listMembers,
      addMember,
      removeMember,
    });
  }).pipe(Effect.withSpan('GroupsServiceLive.initialize')),
) as Layer.Layer<GroupsService, never, MsGraphHttpClient | ApplicationAuth>;
