import { Effect, Layer, Match } from "effect"
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

const narrowToRateLimitOrInvalidRequest = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    () => new RateLimitedError({ retryAfter: 0, resource: "groups" }),
  ),
)

const narrowToRateLimitOrNotFound = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.orElse(
    () => new ResourceNotFoundError({ resource: "group", id: "unknown" }),
  ),
)

const narrowToRateLimitNotFoundOrInvalidRequest = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    () => new RateLimitedError({ retryAfter: 0, resource: "groups" }),
  ),
)

export const GroupsServiceLive = Layer.effect(
  GroupsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    const list = Effect.fn("GroupsService.list")(
      function* (params?: ODataParams<Group>) {
        const qs = params ? buildQueryString<Group>(params as ODataParams<Group>) : ""
        return yield* http.get(`/groups${qs}`, GroupPageSchema).pipe(
          Effect.mapError(narrowToRateLimitOrInvalidRequest),
        )
      },
    )

    const getById = Effect.fn("GroupsService.getById")(
      function* (groupId: string) {
        return yield* http
          .get(`/groups/${groupId}`, GroupSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const listMembers = Effect.fn("GroupsService.listMembers")(
      function* (groupId: string) {
        return yield* http
          .get(`/groups/${groupId}/members`, UserPageSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const addMember = Effect.fn("GroupsService.addMember")(
      function* (groupId: string, userId: string) {
        return yield* http
          .postVoid(`/groups/${groupId}/members/$ref`, {
            "@odata.id": `${GRAPH_BASE_URL}/directoryObjects/${userId}`,
          })
          .pipe(Effect.mapError(narrowToRateLimitNotFoundOrInvalidRequest))
      },
    )

    const removeMember = Effect.fn("GroupsService.removeMember")(
      function* (groupId: string, userId: string) {
        return yield* http
          .delete(`/groups/${groupId}/members/${userId}/$ref`)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    return GroupsService.of({
      list,
      getById,
      listMembers,
      addMember,
      removeMember,
    })
  }),
) as Layer.Layer<
  GroupsService,
  never,
  MsGraphHttpClient | ApplicationAuth
>
