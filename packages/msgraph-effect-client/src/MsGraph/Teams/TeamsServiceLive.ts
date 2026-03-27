import { Effect, Layer, Match } from "effect"
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

const narrowToRateLimit = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource: "teams" })),
)

const narrowToRateLimitOrNotFound = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.orElse(
    () => new ResourceNotFoundError({ resource: "team", id: "unknown" }),
  ),
)

const narrowToRateLimitNotFoundOrInsufficient = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.tag("InsufficientPermissions", (e) => e),
  Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource: "teams" })),
)

export const TeamsServiceLive = Layer.effect(
  TeamsService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    const listTeams = Effect.fn("TeamsService.listTeams")(
      function* (params?: ODataParams<Team>) {
        const qs = params ? buildQueryString<Team>(params as ODataParams<Team>) : ""
        return yield* http.get(`/me/joinedTeams${qs}`, TeamPageSchema).pipe(
          Effect.mapError(narrowToRateLimit),
        )
      },
    )

    const getTeam = Effect.fn("TeamsService.getTeam")(
      function* (teamId: string) {
        return yield* http
          .get(`/teams/${teamId}`, TeamSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const listChannels = Effect.fn("TeamsService.listChannels")(
      function* (teamId: string) {
        return yield* http
          .get(`/teams/${teamId}/channels`, ChannelPageSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const listMessages = Effect.fn("TeamsService.listMessages")(
      function* (
        teamId: string,
        channelId: string,
        params?: ODataParams<ChatMessage>,
      ) {
        const qs = params
          ? buildQueryString<ChatMessage>(params as ODataParams<ChatMessage>)
          : ""
        return yield* http
          .get(
            `/teams/${teamId}/channels/${channelId}/messages${qs}`,
            ChatMessagePageSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const sendMessage = Effect.fn("TeamsService.sendMessage")(
      function* (
        teamId: string,
        channelId: string,
        content: string,
        contentType: "text" | "html" = "text",
      ) {
        return yield* http
          .post(
            `/teams/${teamId}/channels/${channelId}/messages`,
            { body: { contentType, content } },
            ChatMessageSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitNotFoundOrInsufficient))
      },
    )

    const replyToMessage = Effect.fn("TeamsService.replyToMessage")(
      function* (
        teamId: string,
        channelId: string,
        messageId: string,
        content: string,
      ) {
        return yield* http
          .post(
            `/teams/${teamId}/channels/${channelId}/messages/${messageId}/replies`,
            { body: { contentType: "text", content } },
            ChatMessageSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    return TeamsService.of({
      listTeams,
      getTeam,
      listChannels,
      listMessages,
      sendMessage,
      replyToMessage,
    })
  }),
) as Layer.Layer<
  TeamsService,
  never,
  MsGraphHttpClient | ApplicationAuth | DelegatedAuth
>
