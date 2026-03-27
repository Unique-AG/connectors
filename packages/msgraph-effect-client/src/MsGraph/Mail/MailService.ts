import { Effect, ServiceMap, Stream } from "effect"
import type {
  InsufficientPermissionsError,
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { ODataParams, ODataPageType } from "../Schemas/OData"
import type { Attachment, MailFolder, Message, SendMailPayload } from "../Schemas/Message"

export class MailService extends ServiceMap.Service<MailService, {
  readonly listMessages: (
    userId: string,
    folderId?: string,
    params?: ODataParams<Message>,
  ) => Effect.Effect<ODataPageType<Message>, RateLimitedError | InvalidRequestError>

  readonly getMessage: (
    userId: string,
    messageId: string,
    params?: Pick<ODataParams<Message>, "$select" | "$expand">,
  ) => Effect.Effect<Message, ResourceNotFoundError | RateLimitedError>

  readonly send: (
    userId: string,
    payload: SendMailPayload,
  ) => Effect.Effect<void, RateLimitedError | InsufficientPermissionsError | InvalidRequestError>

  readonly reply: (
    userId: string,
    messageId: string,
    comment: string,
  ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>

  readonly move: (
    userId: string,
    messageId: string,
    destinationFolderId: string,
  ) => Effect.Effect<Message, ResourceNotFoundError | RateLimitedError>

  readonly listFolders: (
    userId: string,
  ) => Effect.Effect<ODataPageType<MailFolder>, RateLimitedError>

  readonly listAttachments: (
    userId: string,
    messageId: string,
  ) => Effect.Effect<ReadonlyArray<Attachment>, ResourceNotFoundError | RateLimitedError>

  readonly downloadAttachment: (
    userId: string,
    messageId: string,
    attachmentId: string,
  ) => Effect.Effect<Stream.Stream<Uint8Array, RateLimitedError>, ResourceNotFoundError>
}>()(
  "MsGraph/MailService",
) {}
