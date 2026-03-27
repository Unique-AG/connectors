import { Effect, Layer, Option, Stream, pipe } from "effect"
import { DelegatedAuth } from "../Auth/MsGraphAuth"
import type { MailPermissions } from "../Auth/Permissions"
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

const narrowToRateLimitOrInvalid = (
  error: MsGraphError,
): RateLimitedError | InvalidRequestError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "InvalidRequest") return error as InvalidRequestError
  return new InvalidRequestError({
    code: error._tag,
    message: "Unexpected error",
    target: Option.none(),
    details: [],
  })
}

const narrowToSendErrors = (
  error: MsGraphError,
): RateLimitedError | InsufficientPermissionsError | InvalidRequestError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "InsufficientPermissions") return error as InsufficientPermissionsError
  if (error._tag === "InvalidRequest") return error as InvalidRequestError
  return new InvalidRequestError({
    code: error._tag,
    message: "Unexpected error",
    target: Option.none(),
    details: [],
  })
}

const narrowToNotFoundOrRateLimit = (
  error: MsGraphError,
): ResourceNotFoundError | RateLimitedError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
  return new ResourceNotFoundError({ resource: "Message", id: "unknown" })
}

export const MailServiceLive: Layer.Layer<
  MailService,
  never,
  MsGraphHttpClient | ReturnType<typeof DelegatedAuth<MailPermissions>>
> = Layer.effect(
  MailService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const listMessages = (
      userId: string,
      folderId?: string,
      params?: ODataParams<Message>,
    ) => {
      const basePath = folderId
        ? `/users/${encodeURIComponent(userId)}/mailFolders/${encodeURIComponent(folderId)}/messages`
        : `/users/${encodeURIComponent(userId)}/messages`
      return pipe(
        client.get(`${basePath}${params ? buildQueryString(params) : ""}`, MessagePageSchema),
        Effect.mapError(narrowToRateLimitOrInvalid),
      )
    }

    const getMessage = (
      userId: string,
      messageId: string,
      params?: Pick<ODataParams<Message>, "$select" | "$expand">,
    ) =>
      pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}${params ? buildQueryString(params) : ""}`,
          MessageSchema,
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const send = (userId: string, payload: SendMailPayload) =>
      pipe(
        client.postVoid(`/users/${encodeURIComponent(userId)}/sendMail`, payload),
        Effect.mapError(narrowToSendErrors),
      )

    const reply = (userId: string, messageId: string, comment: string) =>
      pipe(
        client.postVoid(
          `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/reply`,
          { comment },
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const move = (userId: string, messageId: string, destinationFolderId: string) =>
      pipe(
        client.post(
          `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/move`,
          { destinationId: destinationFolderId },
          MoveResponseSchema,
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const listFolders = (userId: string) =>
      pipe(
        client.get(`/users/${encodeURIComponent(userId)}/mailFolders`, MailFolderPageSchema),
        Effect.mapError((error): RateLimitedError => {
          if (error._tag === "RateLimitedError") return error as RateLimitedError
          return new RateLimitedError({ retryAfter: 0, resource: `/users/${userId}/mailFolders` })
        }),
      )

    const listAttachments = (userId: string, messageId: string) =>
      pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments`,
          AttachmentPageSchema,
        ),
        Effect.map((page) => page.value),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const downloadAttachment = (userId: string, messageId: string, attachmentId: string) =>
      pipe(
        client.stream(
          `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}/$value`,
        ),
        Effect.flatMap((byteStream) =>
          Effect.succeed(
            Stream.mapError(byteStream, (error): RateLimitedError => {
              if (error._tag === "RateLimitedError") return error as RateLimitedError
              return new RateLimitedError({
                retryAfter: 0,
                resource: `/users/${userId}/messages/${messageId}/attachments/${attachmentId}/$value`,
              })
            }),
          ),
        ),
        Effect.mapError((error): ResourceNotFoundError => {
          if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
          return new ResourceNotFoundError({ resource: "Attachment", id: attachmentId })
        }),
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
