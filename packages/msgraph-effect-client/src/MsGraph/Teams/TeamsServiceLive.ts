import { Effect, Layer, pipe } from "effect"
import type { AuthFlow, MsGraphAuth } from "../Auth/MsGraphAuth"
import type { TeamsPermissions } from "../Auth/Permissions"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ChannelSchema, ChatMessageSchema, TeamSchema } from "../Schemas/Team"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import type { ChatMessage, Team } from "../Schemas/Team"
import { TeamsService } from "./TeamsService"

const TeamPageSchema = ODataPage(TeamSchema)
const ChannelPageSchema = ODataPage(ChannelSchema)
const ChatMessagePageSchema = ODataPage(ChatMessageSchema)

export const TeamsServiceLive = Layer.effect(
  TeamsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    return TeamsService.of({
      listTeams: (params) => {
        const qs = params ? buildQueryString<Team>(params as ODataParams<Team>) : ""
        return http.get(`/me/joinedTeams${qs}`, TeamPageSchema)
      },

      getTeam: (teamId) => http.get(`/teams/${teamId}`, TeamSchema),

      listChannels: (teamId) =>
        http.get(`/teams/${teamId}/channels`, ChannelPageSchema),

      listMessages: (teamId, channelId, params) => {
        const qs = params
          ? buildQueryString<ChatMessage>(params as ODataParams<ChatMessage>)
          : ""
        return http.get(
          `/teams/${teamId}/channels/${channelId}/messages${qs}`,
          ChatMessagePageSchema,
        )
      },

      sendMessage: (teamId, channelId, content, contentType = "text") =>
        pipe(
          http.post(
            `/teams/${teamId}/channels/${channelId}/messages`,
            { body: { contentType, content } },
            ChatMessageSchema,
          ),
        ),

      replyToMessage: (teamId, channelId, messageId, content) =>
        http.post(
          `/teams/${teamId}/channels/${channelId}/messages/${messageId}/replies`,
          { body: { contentType: "text", content } },
          ChatMessageSchema,
        ),
    })
  }),
) as Layer.Layer<
  TeamsService,
  never,
  MsGraphHttpClient | MsGraphAuth<AuthFlow, TeamsPermissions>
>
