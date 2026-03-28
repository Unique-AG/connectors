import { Effect, Layer, Match, Stream } from 'effect';
import { DelegatedAuth } from '../Auth/MsGraphAuth';
import { toNotFoundOrRateLimit, toRateLimit, toRateLimitOrInvalid } from '../Errors/errorNarrowers';
import type { MsGraphError } from '../Errors/errors';
import {
  InsufficientPermissionsError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../Errors/errors';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { Message, SendMailPayload } from '../Schemas/Message';
import { AttachmentSchema, MailFolderSchema, MessageSchema } from '../Schemas/Message';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import { MailService } from './MailService';

const MessagePageSchema = ODataPage(MessageSchema);
const MailFolderPageSchema = ODataPage(MailFolderSchema);
const AttachmentPageSchema = ODataPage(AttachmentSchema);

const MoveResponseSchema = MessageSchema;

const narrowToSendErrors = Match.type<MsGraphError>().pipe(
  Match.tag('RateLimitedError', (e) => e),
  Match.tag('InsufficientPermissions', (e) => e),
  Match.tag('InvalidRequest', (e) => e),
  Match.orElse(
    (e) =>
      new InsufficientPermissionsError({
        requiredScope: e._tag,
        grantedScopes: [],
      }),
  ),
);

export const MailServiceLive: Layer.Layer<MailService, never, MsGraphHttpClient | DelegatedAuth> =
  Layer.effect(
    MailService,
    Effect.gen(function* () {
      const client = yield* MsGraphHttpClient;

      const listMessages = Effect.fn('MailService.listMessages')(
        function* (userId: string, folderId?: string, params?: ODataParams<Message>) {
          const basePath = folderId
            ? `/users/${encodeURIComponent(userId)}/mailFolders/${encodeURIComponent(folderId)}/messages`
            : `/users/${encodeURIComponent(userId)}/messages`;
          const path = params ? `${basePath}${buildQueryString(params)}` : basePath;
          return yield* client
            .get(path, MessagePageSchema)
            .pipe(Effect.mapError(toRateLimitOrInvalid(basePath)));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'listMessages' }),
      );

      const getMessage = Effect.fn('MailService.getMessage')(
        function* (
          userId: string,
          messageId: string,
          params?: Pick<ODataParams<Message>, '$select' | '$expand'>,
        ) {
          const basePath = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}`;
          const path = params ? `${basePath}${buildQueryString(params)}` : basePath;
          return yield* client
            .get(path, MessageSchema)
            .pipe(Effect.mapError(toNotFoundOrRateLimit(basePath)));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'getMessage' }),
      );

      const send = Effect.fn('MailService.send')(
        function* (userId: string, payload: SendMailPayload) {
          return yield* client
            .postVoid(`/users/${encodeURIComponent(userId)}/sendMail`, payload)
            .pipe(Effect.mapError(narrowToSendErrors));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'send' }),
      );

      const reply = Effect.fn('MailService.reply')(
        function* (userId: string, messageId: string, comment: string) {
          const path = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/reply`;
          return yield* client
            .postVoid(path, { comment })
            .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'reply' }),
      );

      const move = Effect.fn('MailService.move')(
        function* (userId: string, messageId: string, destinationFolderId: string) {
          const path = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/move`;
          return yield* client
            .post(path, { destinationId: destinationFolderId }, MoveResponseSchema)
            .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'move' }),
      );

      const listFolders = Effect.fn('MailService.listFolders')(
        function* (userId: string) {
          const path = `/users/${encodeURIComponent(userId)}/mailFolders`;
          return yield* client
            .get(path, MailFolderPageSchema)
            .pipe(Effect.mapError(toRateLimit(path)));
        },
        Effect.annotateLogs({ service: 'MailService', method: 'listFolders' }),
      );

      const listAttachments = Effect.fn('MailService.listAttachments')(
        function* (userId: string, messageId: string) {
          const path = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments`;
          return yield* client.get(path, AttachmentPageSchema).pipe(
            Effect.map((page) => page.value),
            Effect.mapError(toNotFoundOrRateLimit(path)),
          );
        },
        Effect.annotateLogs({ service: 'MailService', method: 'listAttachments' }),
      );

      const downloadAttachment = Effect.fn('MailService.downloadAttachment')(
        function* (userId: string, messageId: string, attachmentId: string) {
          const streamPath = `/users/${encodeURIComponent(userId)}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}/$value`;
          const byteStream = yield* client.stream(streamPath).pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag('ResourceNotFound', (e) => e),
                Match.orElse(
                  () =>
                    new ResourceNotFoundError({
                      resource: 'Attachment',
                      id: attachmentId,
                    }),
                ),
              ),
            ),
          );
          return Stream.mapError(
            byteStream,
            Match.type<MsGraphError>().pipe(
              Match.tag('RateLimitedError', (e) => e),
              Match.orElse(
                () =>
                  new RateLimitedError({
                    retryAfter: 0,
                    resource: streamPath,
                  }),
              ),
            ),
          );
        },
        Effect.annotateLogs({ service: 'MailService', method: 'downloadAttachment' }),
      );

      return MailService.of({
        listMessages,
        getMessage,
        send,
        reply,
        move,
        listFolders,
        listAttachments,
        downloadAttachment,
      });
    }).pipe(Effect.withSpan('MailServiceLive.initialize')),
  );
