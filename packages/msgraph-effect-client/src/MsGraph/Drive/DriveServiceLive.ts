import { Effect, Layer, Schema, Stream, pipe } from "effect"
import type { AuthFlow, MsGraphAuth } from "../Auth/MsGraphAuth"
import type { DrivePermissions } from "../Auth/Permissions"
import {
  InvalidRequestError,
  QuotaExceededError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import {
  DriveItemSchema,
  SharingLinkSchema,
  UploadSessionSchema,
} from "../Schemas/DriveItem"
import type { DriveItem } from "../Schemas/DriveItem"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import { DriveService } from "./DriveService"

const CHUNK_SIZE = 320 * 1024

const DriveItemPageSchema = ODataPage(DriveItemSchema)

const collectStream = (
  stream: Stream.Stream<Uint8Array>,
): Effect.Effect<Uint8Array, never> =>
  Effect.gen(function* () {
    const chunks = yield* Stream.runCollect(stream)
    const totalLength = Array.from(chunks).reduce(
      (acc, chunk) => acc + chunk.length,
      0,
    )
    const result = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of chunks) {
      result.set(chunk, offset)
      offset += chunk.length
    }
    return result
  })

const uploadChunks = (
  uploadUrl: string,
  content: Stream.Stream<Uint8Array>,
  fileSize: number,
): Effect.Effect<DriveItem, MsGraphError> =>
  Effect.gen(function* () {
    const allBytes = yield* collectStream(content)

    let position = 0
    let lastResponse: unknown = null

    while (position < allBytes.length) {
      const end = Math.min(position + CHUNK_SIZE, allBytes.length)
      const chunk = allBytes.slice(position, end)
      const contentRange = `bytes ${position}-${end - 1}/${fileSize}`

      const response = yield* Effect.tryPromise({
        try: () =>
          fetch(uploadUrl, {
            method: "PUT",
            headers: {
              "Content-Range": contentRange,
              "Content-Length": String(chunk.length),
              "Content-Type": "application/octet-stream",
            },
            body: chunk,
          }).then((r) => r.json()),
        catch: () =>
          new InvalidRequestError({
            code: "UploadChunkFailed",
            message: "Failed to upload chunk to upload session URL",
            target: { _tag: "None" } as never,
            details: [],
          }),
      })

      if (
        response !== null &&
        typeof response === "object" &&
        "id" in response
      ) {
        lastResponse = response
      }

      position = end
    }

    if (lastResponse === null) {
      return yield* Effect.fail(
        new InvalidRequestError({
          code: "UploadSessionFailed",
          message: "Upload session completed without returning a DriveItem",
          target: { _tag: "None" } as never,
          details: [],
        }),
      )
    }

    return yield* Effect.mapError(
      Schema.decodeUnknown(DriveItemSchema)(lastResponse),
      () =>
        new InvalidRequestError({
          code: "UploadResponseDecodeFailed",
          message: "Upload session response did not match DriveItem schema",
          target: { _tag: "None" } as never,
          details: [],
        }),
    )
  })

const narrowToQuotaOrRateLimit = (
  error: MsGraphError,
): QuotaExceededError | RateLimitedError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "QuotaExceeded") return error as QuotaExceededError
  return new RateLimitedError({ retryAfter: 0, resource: "drive" })
}

const narrowToNotFoundOrRateLimit = (
  error: MsGraphError,
): ResourceNotFoundError | RateLimitedError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
  return new ResourceNotFoundError({ resource: "driveItem", id: "unknown" })
}

export const DriveServiceLive = Layer.effect(
  DriveService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    return DriveService.of({
      listItems: (driveId, folderId, params) => {
        const basePath = folderId
          ? `/drives/${driveId}/items/${folderId}/children`
          : `/drives/${driveId}/root/children`
        const qs = params
          ? buildQueryString<DriveItem>(params as ODataParams<DriveItem>)
          : ""
        return pipe(
          http.get(`${basePath}${qs}`, DriveItemPageSchema),
          Effect.mapError(narrowToNotFoundOrRateLimit),
        )
      },

      getItem: (driveId, itemId) =>
        pipe(
          http.get(`/drives/${driveId}/items/${itemId}`, DriveItemSchema),
          Effect.mapError(narrowToNotFoundOrRateLimit),
        ),

      getByPath: (driveId, path) =>
        pipe(
          http.get(`/drives/${driveId}/root:/${path}`, DriveItemSchema),
          Effect.mapError(narrowToNotFoundOrRateLimit),
        ),

      downloadContent: (driveId, itemId) =>
        pipe(
          http.stream(`/drives/${driveId}/items/${itemId}/content`),
          Effect.map((stream) =>
            Stream.mapError(stream, (error): RateLimitedError => {
              if (error._tag === "RateLimitedError")
                return error as RateLimitedError
              return new RateLimitedError({
                retryAfter: 0,
                resource: `/drives/${driveId}/items/${itemId}/content`,
              })
            }),
          ),
          Effect.mapError((error): ResourceNotFoundError => {
            if (error._tag === "ResourceNotFound")
              return error as ResourceNotFoundError
            return new ResourceNotFoundError({
              resource: "driveItem",
              id: itemId,
            })
          }),
        ),

      uploadSmall: (driveId, parentPath, fileName, _content, _contentType) =>
        pipe(
          http.post(
            `/drives/${driveId}/root:/${parentPath}/${fileName}:/content`,
            {},
            DriveItemSchema,
          ),
          Effect.mapError(narrowToQuotaOrRateLimit),
        ),

      uploadSession: (driveId, parentPath, fileName, content, fileSize) =>
        pipe(
          Effect.gen(function* () {
            const session = yield* http.post(
              `/drives/${driveId}/root:/${parentPath}/${fileName}:/createUploadSession`,
              { item: { "@microsoft.graph.conflictBehavior": "replace" } },
              UploadSessionSchema,
            )
            return yield* uploadChunks(session.uploadUrl, content, fileSize)
          }),
          Effect.mapError(narrowToQuotaOrRateLimit),
        ),

      createFolder: (driveId, parentId, name) =>
        pipe(
          http.post(
            `/drives/${driveId}/items/${parentId}/children`,
            {
              name,
              folder: {},
              "@microsoft.graph.conflictBehavior": "rename",
            },
            DriveItemSchema,
          ),
        ),

      delete: (driveId, itemId) =>
        pipe(
          http.delete(`/drives/${driveId}/items/${itemId}`),
          Effect.mapError(narrowToNotFoundOrRateLimit),
        ),

      search: (driveId, query) =>
        pipe(
          http.get(
            `/drives/${driveId}/root/search(q='${encodeURIComponent(query)}')`,
            DriveItemPageSchema,
          ),
          Effect.mapError((error): RateLimitedError => {
            if (error._tag === "RateLimitedError")
              return error as RateLimitedError
            return new RateLimitedError({
              retryAfter: 0,
              resource: `/drives/${driveId}/root/search`,
            })
          }),
        ),

      createSharingLink: (driveId, itemId, type, scope) =>
        pipe(
          http.post(
            `/drives/${driveId}/items/${itemId}/createLink`,
            { type, scope },
            SharingLinkSchema,
          ),
          Effect.mapError(narrowToNotFoundOrRateLimit),
        ),
    })
  }),
) as Layer.Layer<
  DriveService,
  never,
  MsGraphHttpClient | MsGraphAuth<AuthFlow, DrivePermissions>
>
