import { Effect, Layer, Stream, pipe } from "effect"
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

const narrowToRateLimit = (error: MsGraphError): RateLimitedError | InvalidRequestError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  return new InvalidRequestError({
    code: error._tag,
    message: "Unexpected error",
    target: undefined,
    details: [],
  })
}

const narrowToNotFoundOrRateLimit = (error: MsGraphError): ResourceNotFoundError | RateLimitedError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
  return new ResourceNotFoundError({ resource: "User", id: "unknown" })
}

export const UsersServiceLive: Layer.Layer<
  UsersService,
  never,
  MsGraphHttpClient | ApplicationAuth
> = Layer.effect(
  UsersService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const list = (
      params?: ODataParams<User>,
    ) =>
      pipe(
        client.get(`/users${params ? buildQueryString(params) : ""}`, UserPageSchema),
        Effect.mapError(narrowToRateLimit),
      )

    const getById = (
      id: string,
      params?: Pick<ODataParams<User>, "$select" | "$expand">,
    ) =>
      pipe(
        client.get(`/users/${encodeURIComponent(id)}${params ? buildQueryString(params) : ""}`, UserSchema),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const me = (
      params?: Pick<ODataParams<User>, "$select" | "$expand">,
    ) =>
      pipe(
        client.get(`/me${params ? buildQueryString(params) : ""}`, UserSchema),
        Effect.mapError((error): RateLimitedError => {
          if (error._tag === "RateLimitedError") return error as RateLimitedError
          return new RateLimitedError({ retryAfter: 0, resource: "/me" })
        }),
      )

    const listDirectReports = (
      userId: string,
      params?: ODataParams<User>,
    ) =>
      pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/directReports${params ? buildQueryString(params) : ""}`,
          UserPageSchema,
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const getManager = (userId: string) =>
      pipe(
        client.get(`/users/${encodeURIComponent(userId)}/manager`, UserSchema),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const getPhoto = (
      userId: string,
    ) =>
      pipe(
        client.stream(`/users/${encodeURIComponent(userId)}/photo/$value`),
        Effect.flatMap((byteStream) =>
          Effect.succeed(
            Stream.mapError(byteStream, (error): RateLimitedError => {
              if (error._tag === "RateLimitedError") return error as RateLimitedError
              return new RateLimitedError({ retryAfter: 0, resource: `/users/${userId}/photo/$value` })
            }),
          ),
        ),
        Effect.mapError((error): ResourceNotFoundError => {
          if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
          return new ResourceNotFoundError({ resource: "UserPhoto", id: userId })
        }),
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
