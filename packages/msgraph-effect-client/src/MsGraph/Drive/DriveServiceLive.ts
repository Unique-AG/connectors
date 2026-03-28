import { Effect, Layer, Match, Schema, Stream } from 'effect';
import type { ApplicationAuth, DelegatedAuth } from '../Auth/MsGraphAuth';
import { toNotFoundOrRateLimit } from '../Errors/errorNarrowers';
import type { MsGraphError } from '../Errors/errors';
import { InvalidRequestError, RateLimitedError, ResourceNotFoundError } from '../Errors/errors';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { DriveItem } from '../Schemas/DriveItem';
import { DriveItemSchema, SharingLinkSchema, UploadSessionSchema } from '../Schemas/DriveItem';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import { DriveService } from './DriveService';

const CHUNK_SIZE = 320 * 1024;

const DriveItemPageSchema = ODataPage(DriveItemSchema);

const collectStream = Effect.fn('DriveService.collectStream')(
  function* (stream: Stream.Stream<Uint8Array>) {
    const chunks = yield* Stream.runCollect(stream);
    const totalLength = Array.from(chunks).reduce((acc, chunk) => acc + chunk.length, 0);
    const result = new Uint8Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
      result.set(chunk, offset);
      offset += chunk.length;
    }
    return result;
  },
  Effect.annotateLogs({ service: 'DriveService', method: 'collectStream' }),
);

const uploadChunks = Effect.fn('DriveService.uploadChunks')(
  function* (
    uploadUrl: string,
    content: Stream.Stream<Uint8Array>,
    fileSize: number,
  ): Effect.fn.Return<DriveItem, MsGraphError> {
    const allBytes = yield* collectStream(content);

    let position = 0;
    let lastResponse: unknown = null;

    while (position < allBytes.length) {
      const end = Math.min(position + CHUNK_SIZE, allBytes.length);
      const chunk = allBytes.slice(position, end);
      const contentRange = `bytes ${position}-${end - 1}/${fileSize}`;

      const fetchResponse = yield* Effect.timeoutOrElse(
        Effect.tryPromise({
          try: async () =>
            fetch(uploadUrl, {
              method: 'PUT',
              headers: {
                'Content-Range': contentRange,
                'Content-Length': String(chunk.length),
                'Content-Type': 'application/octet-stream',
              },
              body: chunk,
            }),
          catch: () =>
            new InvalidRequestError({
              code: 'UploadChunkFailed',
              message: 'Failed to upload chunk to upload session URL',
              target: undefined,
              details: [],
            }),
        }),
        {
          duration: '30 seconds',
          orElse: () =>
            Effect.fail(
              new InvalidRequestError({
                code: 'UploadChunkTimeout',
                message: 'Upload chunk timed out',
                target: uploadUrl,
                details: [],
              }),
            ),
        },
      );

      const response = yield* Effect.timeoutOrElse(
        Effect.tryPromise({
          try: async () => fetchResponse.json(),
          catch: () =>
            new InvalidRequestError({
              code: 'UploadChunkFailed',
              message: 'Failed to parse upload chunk response',
              target: undefined,
              details: [],
            }),
        }),
        {
          duration: '30 seconds',
          orElse: () =>
            Effect.fail(
              new InvalidRequestError({
                code: 'UploadChunkResponseTimeout',
                message: 'Parsing upload chunk response timed out',
                target: uploadUrl,
                details: [],
              }),
            ),
        },
      );

      if (response !== null && typeof response === 'object' && 'id' in response) {
        lastResponse = response;
      }

      position = end;
    }

    if (lastResponse === null) {
      return yield* Effect.fail(
        new InvalidRequestError({
          code: 'UploadSessionFailed',
          message: 'Upload session completed without returning a DriveItem',
          target: undefined,
          details: [],
        }),
      );
    }

    return yield* Effect.mapError(
      Schema.decodeUnknownEffect(DriveItemSchema)(lastResponse),
      () =>
        new InvalidRequestError({
          code: 'UploadResponseDecodeFailed',
          message: 'Upload session response did not match DriveItem schema',
          target: undefined,
          details: [],
        }),
    );
  },
  Effect.annotateLogs({ service: 'DriveService', method: 'uploadChunks' }),
);

const narrowToQuotaOrRateLimit = Match.type<MsGraphError>().pipe(
  Match.tag('RateLimitedError', (e) => e),
  Match.tag('QuotaExceeded', (e) => e),
  Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource: 'drive' })),
);

export const DriveServiceLive = Layer.effect(
  DriveService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient;

    const listItems = Effect.fn('DriveService.listItems')(
      function* (driveId: string, folderId?: string, params?: ODataParams<DriveItem>) {
        const basePath = folderId
          ? `/drives/${driveId}/items/${folderId}/children`
          : `/drives/${driveId}/root/children`;
        const qs = params ? buildQueryString<DriveItem>(params as ODataParams<DriveItem>) : '';
        return yield* http
          .get(`${basePath}${qs}`, DriveItemPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(basePath)));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'listItems' }),
    );

    const getItem = Effect.fn('DriveService.getItem')(
      function* (driveId: string, itemId: string) {
        const path = `/drives/${driveId}/items/${itemId}`;
        return yield* http
          .get(path, DriveItemSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'getItem' }),
    );

    const getByPath = Effect.fn('DriveService.getByPath')(
      function* (driveId: string, path: string) {
        const apiPath = `/drives/${driveId}/root:/${path}`;
        return yield* http
          .get(apiPath, DriveItemSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(apiPath)));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'getByPath' }),
    );

    const downloadContent = Effect.fn('DriveService.downloadContent')(
      function* (driveId: string, itemId: string) {
        const streamPath = `/drives/${driveId}/items/${itemId}/content`;
        const stream = yield* http.stream(streamPath).pipe(
          Effect.mapError(
            Match.type<MsGraphError>().pipe(
              Match.tag('ResourceNotFound', (e) => e),
              Match.orElse(
                () =>
                  new ResourceNotFoundError({
                    resource: 'driveItem',
                    id: itemId,
                  }),
              ),
            ),
          ),
        );
        return Stream.mapError(
          stream,
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
      Effect.annotateLogs({ service: 'DriveService', method: 'downloadContent' }),
    );

    const uploadSmall = Effect.fn('DriveService.uploadSmall')(
      function* (
        driveId: string,
        parentPath: string,
        fileName: string,
        _content: Uint8Array,
        _contentType: string,
      ) {
        return yield* http
          .post(`/drives/${driveId}/root:/${parentPath}/${fileName}:/content`, {}, DriveItemSchema)
          .pipe(Effect.mapError(narrowToQuotaOrRateLimit));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'uploadSmall' }),
    );

    const uploadSession = Effect.fn('DriveService.uploadSession')(
      function* (
        driveId: string,
        parentPath: string,
        fileName: string,
        content: Stream.Stream<Uint8Array>,
        fileSize: number,
      ) {
        const session = yield* http
          .post(
            `/drives/${driveId}/root:/${parentPath}/${fileName}:/createUploadSession`,
            { item: { '@microsoft.graph.conflictBehavior': 'replace' } },
            UploadSessionSchema,
          )
          .pipe(Effect.mapError(narrowToQuotaOrRateLimit));
        return yield* uploadChunks(session.uploadUrl, content, fileSize).pipe(
          Effect.mapError(narrowToQuotaOrRateLimit),
        );
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'uploadSession' }),
    );

    const createFolder = Effect.fn('DriveService.createFolder')(
      function* (driveId: string, parentId: string, name: string) {
        const path = `/drives/${driveId}/items/${parentId}/children`;
        return yield* http
          .post(
            path,
            {
              name,
              folder: {},
              '@microsoft.graph.conflictBehavior': 'rename',
            },
            DriveItemSchema,
          )
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag('RateLimitedError', (e) => e),
                Match.tag('InvalidRequest', (e) => e),
                Match.orElse(
                  () =>
                    new RateLimitedError({
                      retryAfter: 0,
                      resource: path,
                    }),
                ),
              ),
            ),
          );
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'createFolder' }),
    );

    const deleteItem = Effect.fn('DriveService.delete')(
      function* (driveId: string, itemId: string) {
        const path = `/drives/${driveId}/items/${itemId}`;
        return yield* http.delete(path).pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'delete' }),
    );

    const search = Effect.fn('DriveService.search')(
      function* (driveId: string, query: string) {
        const path = `/drives/${driveId}/root/search`;
        return yield* http
          .get(
            `/drives/${driveId}/root/search(q='${encodeURIComponent(query)}')`,
            DriveItemPageSchema,
          )
          .pipe(
            Effect.mapError(
              Match.type<MsGraphError>().pipe(
                Match.tag('RateLimitedError', (e) => e),
                Match.orElse(
                  () =>
                    new RateLimitedError({
                      retryAfter: 0,
                      resource: path,
                    }),
                ),
              ),
            ),
          );
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'search' }),
    );

    const createSharingLink = Effect.fn('DriveService.createSharingLink')(
      function* (
        driveId: string,
        itemId: string,
        type: 'view' | 'edit',
        scope: 'anonymous' | 'organization',
      ) {
        const path = `/drives/${driveId}/items/${itemId}/createLink`;
        return yield* http
          .post(path, { type, scope }, SharingLinkSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'DriveService', method: 'createSharingLink' }),
    );

    return DriveService.of({
      listItems,
      getItem,
      getByPath,
      downloadContent,
      uploadSmall,
      uploadSession,
      createFolder,
      delete: deleteItem,
      search,
      createSharingLink,
    });
  }).pipe(Effect.withSpan('DriveServiceLive.initialize')),
) as Layer.Layer<DriveService, never, MsGraphHttpClient | ApplicationAuth | DelegatedAuth>;
