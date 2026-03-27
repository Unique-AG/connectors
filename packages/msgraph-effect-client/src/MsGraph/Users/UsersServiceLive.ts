import { Effect, Layer, Match, Stream } from "effect"
import { ApplicationAuth } from "../Auth/MsGraphAuth"
import {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import { UserSchema } from "../Schemas/User"
import type { User } from "../Schemas/User"
import { UsersService } from "./UsersService"

const UserPageSchema = ODataPage(UserSchema)

const narrowToRateLimit = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.orElse(
    (e) =>
      new InvalidRequestError({
        code: e._tag,
        message: "Unexpected error",
        target: undefined,
        details: [],
      }),
  ),
)

const narrowToNotFoundOrRateLimit = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.orElse(() => new ResourceNotFoundError({ resource: "User", id: "unknown" })),
)

const narrowToRateLimitForMe = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource: "/me" })),
)

export const UsersServiceLive: Layer.Layer<
  UsersService,
  never,
  MsGraphHttpClient | ApplicationAuth
> = Layer.effect(
  UsersService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const list = Effect.fn("UsersService.list")(
      function* (params?: ODataParams<User>) {
        const path = params ? `/users${buildQueryString(params)}` : "/users"
        return yield* client.get(path, UserPageSchema).pipe(
          Effect.mapError(narrowToRateLimit),
        )
      },
    )

    const getById = Effect.fn("UsersService.getById")(
      function* (
        id: string,
        params?: Pick<ODataParams<User>, "$select" | "$expand">,
      ) {
        const path = params
          ? `/users/${encodeURIComponent(id)}${buildQueryString(params)}`
          : `/users/${encodeURIComponent(id)}`
        return yield* client.get(path, UserSchema).pipe(
          Effect.mapError(narrowToNotFoundOrRateLimit),
        )
      },
    )

    const me = Effect.fn("UsersService.me")(
      function* (params?: Pick<ODataParams<User>, "$select" | "$expand">) {
        const path = params ? `/me${buildQueryString(params)}` : "/me"
        return yield* client.get(path, UserSchema).pipe(
          Effect.mapError(narrowToRateLimitForMe),
        )
      },
    )

    const listDirectReports = Effect.fn("UsersService.listDirectReports")(
      function* (userId: string, params?: ODataParams<User>) {
        const path = params
          ? `/users/${encodeURIComponent(userId)}/directReports${buildQueryString(params)}`
          : `/users/${encodeURIComponent(userId)}/directReports`
        return yield* client.get(path, UserPageSchema).pipe(
          Effect.mapError(narrowToNotFoundOrRateLimit),
        )
      },
    )

    const getManager = Effect.fn("UsersService.getManager")(
      function* (userId: string) {
        return yield* client
          .get(`/users/${encodeURIComponent(userId)}/manager`, UserSchema)
          .pipe(Effect.mapError(narrowToNotFoundOrRateLimit))
      },
    )

    const getPhoto = Effect.fn("UsersService.getPhoto")(
      function* (userId: string) {
        const byteStream = yield* client
          .stream(`/users/${encodeURIComponent(userId)}/photo/$value`)
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag("ResourceNotFound", (e) => e),
                Match.orElse(
                  () =>
                    new ResourceNotFoundError({
                      resource: "UserPhoto",
                      id: userId,
                    }),
                ),
              ),
            ),
          )
        return Stream.mapError(
          byteStream,
          Match.type<MsGraphError>().pipe(
            Match.tag("RateLimitedError", (e) => e),
            Match.orElse(
              () =>
                new RateLimitedError({
                  retryAfter: 0,
                  resource: `/users/${userId}/photo/$value`,
                }),
            ),
          ),
        )
      },
    )

    return UsersService.of({
      list,
      getById,
      me,
      listDirectReports,
      getManager,
      getPhoto,
    })
  }),
)
