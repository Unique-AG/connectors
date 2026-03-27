import { Effect, Schema } from "effect"
import { BatchItemError, type MsGraphError } from "../Errors/errors"
import { decodeGraphError } from "../Errors/errorDecoder"
import type { MsGraphHttpClient } from "./MsGraphHttpClient"

export interface BatchRequestItem {
  readonly id: string
  readonly method: "GET" | "POST" | "PATCH" | "DELETE"
  readonly url: string
  readonly body?: unknown
  readonly headers?: Record<string, string>
}

export interface BatchResponseItem {
  readonly id: string
  readonly status: number
  readonly headers?: Record<string, string>
  readonly body?: unknown
  readonly error?: BatchItemError
}

const BatchResponseBodySchema = Schema.Struct({
  responses: Schema.Array(
    Schema.Struct({
      id: Schema.String,
      status: Schema.Number,
      headers: Schema.optional(Schema.Record(Schema.String, Schema.String)),
      body: Schema.optional(Schema.Unknown),
    }),
  ),
})

const decodeBatchItem = (
  rawItem: {
    readonly id: string
    readonly status: number
    readonly headers?: Record<string, string>
    readonly body?: unknown
  },
): BatchResponseItem => {
  const isError = rawItem.status >= 400
  if (!isError) {
    return { id: rawItem.id, status: rawItem.status, headers: rawItem.headers, body: rawItem.body }
  }

  const headers = rawItem.headers ?? {}
  const inner: MsGraphError = decodeGraphError(rawItem.status, rawItem.body, headers, rawItem.id)
  const error = new BatchItemError({
    requestId: rawItem.id,
    statusCode: rawItem.status,
    inner,
  })

  return { id: rawItem.id, status: rawItem.status, headers: rawItem.headers, body: rawItem.body, error }
}

export const executeBatch = (
  client: MsGraphHttpClient["Service"],
  requests: ReadonlyArray<BatchRequestItem>,
): Effect.Effect<ReadonlyArray<BatchResponseItem>, MsGraphError> => {
  if (requests.length > 20) {
    return Effect.die(new Error("Microsoft Graph $batch supports at most 20 requests per batch"))
  }

  const batchBody = {
    requests: requests.map((req) => ({
      id: req.id,
      method: req.method,
      url: req.url,
      ...(req.body !== undefined ? { body: req.body } : {}),
      ...(req.headers ? { headers: req.headers } : {}),
    })),
  }

  return Effect.flatMap(
    client.post("/$batch", batchBody, BatchResponseBodySchema),
    (batchResponse) =>
      Effect.succeed(batchResponse.responses.map(decodeBatchItem)),
  )
}
