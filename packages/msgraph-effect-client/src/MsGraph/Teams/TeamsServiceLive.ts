import { Effect, Layer, pipe } from "effect"
import type { ApplicationAuth, DelegatedAuth } from "../Auth/MsGraphAuth"
import {
  InsufficientPermissionsError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
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

    const narrowToRateLimit = (error: MsGraphError): RateLimitedError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      return new RateLimitedError({ retryAfter: 0, resource: "teams" })
    }

    const narrowToRateLimitOrNotFound = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      return new ResourceNotFoundError({ resource: "team", id: "unknown" })
    }

    const narrowToRateLimitNotFoundOrInsufficient = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError | InsufficientPermissionsError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      if (error._tag === "InsufficientPermissions") return error as InsufficientPermissionsError
      return new RateLimitedError({ retryAfter: 0, resource: "teams" })
    }

    return TeamsService.of({
      listTeams: (params?) => {
        const qs = params ? buildQueryString<Team>(params as ODataParams<Team>) : ""
        return Effect.mapError(
          http.get(`/me/joinedTeams${qs}`, TeamPageSchema),
          narrowToRateLimit,
        )
      },

      getTeam: (teamId) =>
        Effect.mapError(
          http.get(`/teams/${teamId}`, TeamSchema),
          narrowToRateLimitOrNotFound,
        ),

      listChannels: (teamId) =>
        Effect.mapError(
          http.get(`/teams/${teamId}/channels`, ChannelPageSchema),
          narrowToRateLimitOrNotFound,
        ),

      listMessages: (teamId, channelId, params?) => {
        const qs = params
          ? buildQueryString<ChatMessage>(params as ODataParams<ChatMessage>)
          : ""
        return Effect.mapError(
          http.get(
            `/teams/${teamId}/channels/${channelId}/messages${qs}`,
            ChatMessagePageSchema,
          ),
          narrowToRateLimitOrNotFound,
        )
      },

      sendMessage: (teamId, channelId, content, contentType = "text") =>
        pipe(
          http.post(
            `/teams/${teamId}/channels/${channelId}/messages`,
            { body: { contentType, content } },
            ChatMessageSchema,
          ),
          Effect.mapError(narrowToRateLimitNotFoundOrInsufficient),
        ),

      replyToMessage: (teamId, channelId, messageId, content) =>
        Effect.mapError(
          http.post(
            `/teams/${teamId}/channels/${channelId}/messages/${messageId}/replies`,
            { body: { contentType: "text", content } },
            ChatMessageSchema,
          ),
          narrowToRateLimitOrNotFound,
        ),
    })
  }),
) as Layer.Layer<
  TeamsService,
  never,
  MsGraphHttpClient | ApplicationAuth | DelegatedAuth
>
