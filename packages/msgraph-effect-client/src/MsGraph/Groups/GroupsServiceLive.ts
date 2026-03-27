import { Effect, Layer } from "effect"
import type { ApplicationAuth } from "../Auth/MsGraphAuth"
import {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { GroupSchema } from "../Schemas/Group"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import type { Group } from "../Schemas/Group"
import { UserSchema } from "../Schemas/User"
import { GroupsService } from "./GroupsService"

const GroupPageSchema = ODataPage(GroupSchema)
const UserPageSchema = ODataPage(UserSchema)

const GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

export const GroupsServiceLive = Layer.effect(
  GroupsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    const narrowToRateLimitOrInvalidRequest = (
      error: MsGraphError,
    ): RateLimitedError | InvalidRequestError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "InvalidRequest") return error as InvalidRequestError
      return new RateLimitedError({ retryAfter: 0, resource: "groups" })
    }

    const narrowToRateLimitOrNotFound = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      return new ResourceNotFoundError({ resource: "group", id: "unknown" })
    }

    const narrowToRateLimitNotFoundOrInvalidRequest = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError | InvalidRequestError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      if (error._tag === "InvalidRequest") return error as InvalidRequestError
      return new RateLimitedError({ retryAfter: 0, resource: "groups" })
    }

    return GroupsService.of({
      list: (params?) => {
        const qs = params ? buildQueryString<Group>(params as ODataParams<Group>) : ""
        return Effect.mapError(
          http.get(`/groups${qs}`, GroupPageSchema),
          narrowToRateLimitOrInvalidRequest,
        )
      },

      getById: (groupId) =>
        Effect.mapError(
          http.get(`/groups/${groupId}`, GroupSchema),
          narrowToRateLimitOrNotFound,
        ),

      listMembers: (groupId) =>
        Effect.mapError(
          http.get(`/groups/${groupId}/members`, UserPageSchema),
          narrowToRateLimitOrNotFound,
        ),

      addMember: (groupId, userId) =>
        Effect.mapError(
          http.postVoid(`/groups/${groupId}/members/$ref`, {
            "@odata.id": `${GRAPH_BASE_URL}/directoryObjects/${userId}`,
          }),
          narrowToRateLimitNotFoundOrInvalidRequest,
        ),

      removeMember: (groupId, userId) =>
        Effect.mapError(
          http.delete(`/groups/${groupId}/members/${userId}/$ref`),
          narrowToRateLimitOrNotFound,
        ),
    })
  }),
) as Layer.Layer<
  GroupsService,
  never,
  MsGraphHttpClient | ApplicationAuth
>
