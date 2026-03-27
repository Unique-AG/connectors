import { Effect, Layer } from "effect"
import type { MsGraphAuth } from "../Auth/MsGraphAuth"
import type { GroupPermissions } from "../Auth/Permissions"
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

    return GroupsService.of({
      list: (params) => {
        const qs = params ? buildQueryString<Group>(params as ODataParams<Group>) : ""
        return http.get(`/groups${qs}`, GroupPageSchema)
      },

      getById: (groupId) => http.get(`/groups/${groupId}`, GroupSchema),

      listMembers: (groupId) =>
        http.get(`/groups/${groupId}/members`, UserPageSchema),

      addMember: (groupId, userId) =>
        http.postVoid(`/groups/${groupId}/members/$ref`, {
          "@odata.id": `${GRAPH_BASE_URL}/directoryObjects/${userId}`,
        }),

      removeMember: (groupId, userId) =>
        http.delete(`/groups/${groupId}/members/${userId}/$ref`),
    })
  }),
) as Layer.Layer<
  GroupsService,
  never,
  MsGraphHttpClient | MsGraphAuth<"Application", GroupPermissions>
>
