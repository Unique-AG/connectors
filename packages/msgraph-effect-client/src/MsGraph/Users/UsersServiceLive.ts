import { Effect, Layer, Match, Stream } from 'effect';
import { ApplicationAuth } from '../Auth/MsGraphAuth';
import { toNotFoundOrRateLimit, toRateLimit } from '../Errors/errorNarrowers';
import type { MsGraphError } from '../Errors/errors';
import { RateLimitedError, ResourceNotFoundError } from '../Errors/errors';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import type { User } from '../Schemas/User';
import { UserSchema } from '../Schemas/User';
import { UsersService } from './UsersService';

const UserPageSchema = ODataPage(UserSchema);

export const UsersServiceLive: Layer.Layer<
  UsersService,
  never,
  MsGraphHttpClient | ApplicationAuth
> = Layer.effect(
  UsersService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient;

    const list = Effect.fn('UsersService.list')(
      function* (params?: ODataParams<User>) {
        const path = params ? `/users${buildQueryString(params)}` : '/users';
        return yield* client.get(path, UserPageSchema).pipe(Effect.mapError(toRateLimit('/users')));
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'list' }),
    );

    const getById = Effect.fn('UsersService.getById')(
      function* (id: string, params?: Pick<ODataParams<User>, '$select' | '$expand'>) {
        const path = params
          ? `/users/${encodeURIComponent(id)}${buildQueryString(params)}`
          : `/users/${encodeURIComponent(id)}`;
        return yield* client
          .get(path, UserSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(`/users/${id}`)));
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'getById' }),
    );

    const me = Effect.fn('UsersService.me')(
      function* (params?: Pick<ODataParams<User>, '$select' | '$expand'>) {
        const path = params ? `/me${buildQueryString(params)}` : '/me';
        return yield* client.get(path, UserSchema).pipe(Effect.mapError(toRateLimit('/me')));
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'me' }),
    );

    const listDirectReports = Effect.fn('UsersService.listDirectReports')(
      function* (userId: string, params?: ODataParams<User>) {
        const path = params
          ? `/users/${encodeURIComponent(userId)}/directReports${buildQueryString(params)}`
          : `/users/${encodeURIComponent(userId)}/directReports`;
        return yield* client
          .get(path, UserPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(`/users/${userId}/directReports`)));
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'listDirectReports' }),
    );

    const getManager = Effect.fn('UsersService.getManager')(
      function* (userId: string) {
        return yield* client
          .get(`/users/${encodeURIComponent(userId)}/manager`, UserSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(`/users/${userId}/manager`)));
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'getManager' }),
    );

    const getPhoto = Effect.fn('UsersService.getPhoto')(
      function* (userId: string) {
        const byteStream = yield* client
          .stream(`/users/${encodeURIComponent(userId)}/photo/$value`)
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag('ResourceNotFound', (e) => e),
                Match.orElse(
                  () =>
                    new ResourceNotFoundError({
                      resource: 'UserPhoto',
                      id: userId,
                    }),
                ),
              ),
            ),
          );
        return Stream.mapError(
          byteStream,
          Match.type<MsGraphError>().pipe(
            Match.tag('RateLimitedError', (e) => e),
            Match.orElse(
              () =>
                new RateLimitedError({
                  retryAfter: 0,
                  resource: `/users/${userId}/photo/$value`,
                }),
            ),
          ),
        );
      },
      Effect.annotateLogs({ service: 'UsersService', method: 'getPhoto' }),
    );

    return UsersService.of({
      list,
      getById,
      me,
      listDirectReports,
      getManager,
      getPhoto,
    });
  }).pipe(Effect.withSpan('UsersServiceLive.initialize')),
);
