import { Effect, Layer, Match, Stream } from "effect"
import { DelegatedAuth } from "../Auth/MsGraphAuth"
import {
  InsufficientPermissionsError,
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import {
  AttachmentSchema,
  MailFolderSchema,
  MessageSchema,
} from "../Schemas/Message"
import type { Message, SendMailPayload } from "../Schemas/Message"
import { MailService } from "./MailService"

const MessagePageSchema = ODataPage(MessageSchema)
const MailFolderPageSchema = ODataPage(MailFolderSchema)
const AttachmentPageSchema = ODataPage(AttachmentSchema)

const MoveResponseSchema = MessageSchema

const narrowToRateLimitOrInvalid = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
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

const narrowToSendErrors = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("InsufficientPermissions", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
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
  Match.orElse(() => new ResourceNotFoundError({ resource: "Message", id: "unknown" })),
)


export const MailServiceLive: Layer.Layer<
  MailService,
  never,
  MsGraphHttpClient | DelegatedAuth
> = Layer.effect(
  MailService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const listMessages = Effect.fn("MailService.listMessages")(
      function* (
        userId: string,
        folderId?: string,
        params?: ODataParams<Message>,
      ) {
        const basePath = folderId
          ? `/users/${encodeURIComponent(userId)}/mailFolders/${encodeURIComponent(folderId)}/messages`
          : `/users/${encodeURIComponent(userId)}/messages`
        const path = params ? `${basePath}${buildQueryString(params)}` : basePath
        return yield* client.get(path, MessagePageSchema).pipe(
          Effect.mapError(narrowToRateLimitOrInvalid),
        )
      },
    )

    const getMessage = Effect.fn("MailService.getMessage")(
      function* (
        userId: string,
        messageId: string,
        params?: Pick<ODataParams<Message>, "$select" | "$expand">,
      ) {
        const basePath = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}`
        const path = params ? `${basePath}${buildQueryString(params)}` : basePath
        return yield* client.get(path, MessageSchema).pipe(
          Effect.mapError(narrowToNotFoundOrRateLimit),
        )
      },
    )

    const send = Effect.fn("MailService.send")(
      function* (userId: string, payload: SendMailPayload) {
        return yield* client
          .postVoid(`/users/${encodeURIComponent(userId)}/sendMail`, payload)
          .pipe(Effect.mapError(narrowToSendErrors))
      },
    )

    const reply = Effect.fn("MailService.reply")(
      function* (userId: string, messageId: string, comment: string) {
        return yield* client
          .postVoid(
            `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/reply`,
            { comment },
          )
          .pipe(Effect.mapError(narrowToNotFoundOrRateLimit))
      },
    )

    const move = Effect.fn("MailService.move")(
      function* (
        userId: string,
        messageId: string,
        destinationFolderId: string,
      ) {
        return yield* client
          .post(
            `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/move`,
            { destinationId: destinationFolderId },
            MoveResponseSchema,
          )
          .pipe(Effect.mapError(narrowToNotFoundOrRateLimit))
      },
    )

    const listFolders = Effect.fn("MailService.listFolders")(
      function* (userId: string) {
        return yield* client
          .get(`/users/${encodeURIComponent(userId)}/mailFolders`, MailFolderPageSchema)
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag("RateLimitedError", (e) => e),
                Match.orElse(
                  () =>
                    new RateLimitedError({
                      retryAfter: 0,
                      resource: `/users/${userId}/mailFolders`,
                    }),
                ),
              ),
            ),
          )
      },
    )

    const listAttachments = Effect.fn("MailService.listAttachments")(
      function* (userId: string, messageId: string) {
        return yield* client
          .get(
            `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments`,
            AttachmentPageSchema,
          )
          .pipe(
            Effect.map((page) => page.value),
            Effect.mapError(narrowToNotFoundOrRateLimit),
          )
      },
    )

    const downloadAttachment = Effect.fn("MailService.downloadAttachment")(
      function* (userId: string, messageId: string, attachmentId: string) {
        const byteStream = yield* client
          .stream(
            `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}/$value`,
          )
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag("ResourceNotFound", (e) => e),
                Match.orElse(
                  () =>
                    new ResourceNotFoundError({
                      resource: "Attachment",
                      id: attachmentId,
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
                  resource: `/users/${userId}/messages/${messageId}/attachments/${attachmentId}/$value`,
                }),
            ),
          ),
        )
      },
    )

    return MailService.of({
      listMessages,
      getMessage,
      send,
      reply,
      move,
      listFolders,
      listAttachments,
      downloadAttachment,
    })
  }),
)
