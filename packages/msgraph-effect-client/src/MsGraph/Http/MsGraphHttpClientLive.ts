import { HttpClient, HttpClientRequest, HttpClientResponse } from "@effect/platform"
import { Chunk, Effect, Layer, Option, Schema, Stream, pipe } from "effect"
import type { AuthFlow } from "../Auth/MsGraphAuth"
import { MsGraphAuthTag } from "../Auth/MsGraphAuth"
import { InvalidRequestError, TokenExpiredError } from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { decodeGraphError } from "../Errors/errorDecoder"
import type { ODataPageType } from "../Schemas/OData"
import { rateLimitSchedule } from "./RateLimiter"
import { MsGraphHttpClient } from "./MsGraphHttpClient"

const BASE_URL = "https://graph.microsoft.com/v1.0"

const decodeResponse =
  <A, I>(schema: Schema.Schema<A, I>) =>
  (response: HttpClientResponse.HttpClientResponse): Effect.Effect<A, MsGraphError> =>
    pipe(
      response.json,
      Effect.flatMap(Schema.decodeUnknown(schema)),
      Effect.mapError((parseError) =>
        new InvalidRequestError({
          code: "ResponseDecodeFailed",
          message: `Response did not match expected schema: ${String(parseError)}`,
          target: Option.none(),
          details: [],
        }),
      ),
    )

const extractHeaders = (
  response: HttpClientResponse.HttpClientResponse,
): Record<string, string | undefined> => {
  const result: Record<string, string | undefined> = {}
  const raw = response.headers
  const retryAfter = raw["retry-after"] ?? raw["Retry-After"]
  if (retryAfter) result["retry-after"] = Array.isArray(retryAfter) ? String(retryAfter[0]) : String(retryAfter)
  return result
}

const handleErrorResponse = (
  response: HttpClientResponse.HttpClientResponse,
  resource: string,
): Effect.Effect<never, MsGraphError> =>
  pipe(
    response.json,
    Effect.orElseSucceed(() => null),
    Effect.flatMap((body) =>
      Effect.fail(decodeGraphError(response.status, body, extractHeaders(response), resource)),
    ),
  )

export const unfoldPages = <A>(
  firstPage: ODataPageType<A>,
  client: MsGraphHttpClient,
  schema: Schema.Schema<ODataPageType<A>>,
): Stream.Stream<A, MsGraphError> =>
  Stream.unfoldChunkEffect(
    firstPage as ODataPageType<A> | undefined,
    (page) => {
      if (page === undefined) {
        return Effect.succeed(Option.none())
      }

      const chunk = Chunk.fromIterable(page.value)
      const nextLink = page["@odata.nextLink"]

      if (!nextLink) {
        return Effect.succeed(
          Option.some([chunk, undefined as unknown as ODataPageType<A>] as const),
        )
      }

      return pipe(
        client.get(nextLink, schema),
        Effect.map((nextPage) =>
          Option.some([chunk, nextPage as ODataPageType<A>] as const),
        ),
      )
    },
  )

const makeHttpClient = <F extends AuthFlow, P extends string>(
  auth: { acquireToken: Effect.Effect<{ tokenType: string; accessToken: string }, MsGraphError> },
  httpClient: HttpClient.HttpClient,
): MsGraphHttpClient => {
  const authorizeAndExecute = (
    request: HttpClientRequest.HttpClientRequest,
  ): Effect.Effect<HttpClientResponse.HttpClientResponse, MsGraphError> =>
    pipe(
      auth.acquireToken,
      Effect.flatMap((tokenInfo) =>
        pipe(
          request,
          HttpClientRequest.setHeader("Authorization", `${tokenInfo.tokenType} ${tokenInfo.accessToken}`),
          HttpClientRequest.setHeader("Content-Type", "application/json"),
          httpClient.execute,
        ),
      ),
      Effect.mapError((error): MsGraphError => {
        if (error instanceof TokenExpiredError) return error
        return new TokenExpiredError({ expiredAt: Date.now() })
      }),
      Effect.scoped,
    )

  const checkStatus = (
    response: HttpClientResponse.HttpClientResponse,
    resource: string,
  ): Effect.Effect<HttpClientResponse.HttpClientResponse, MsGraphError> => {
    if (response.status >= 200 && response.status < 300) {
      return Effect.succeed(response)
    }
    return handleErrorResponse(response, resource)
  }

  const get = <A, I>(
    path: string,
    schema: Schema.Schema<A, I>,
  ): Effect.Effect<A, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    return pipe(
      authorizeAndExecute(HttpClientRequest.get(url)),
      Effect.flatMap((response) => checkStatus(response, path)),
      Effect.flatMap(decodeResponse(schema)),
      Effect.retry(rateLimitSchedule),
    )
  }

  const post = <A, I>(
    path: string,
    body: unknown,
    schema: Schema.Schema<A, I>,
  ): Effect.Effect<A, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    return pipe(
      Effect.flatMap(
        Effect.tryPromise({
          try: () => Promise.resolve(JSON.stringify(body)),
          catch: () => new InvalidRequestError({ code: "SerializeFailed", message: "Failed to serialize request body", target: Option.none(), details: [] }),
        }),
        (json) => authorizeAndExecute(
          HttpClientRequest.post(url).pipe(
            HttpClientRequest.setHeader("Content-Type", "application/json"),
            HttpClientRequest.bodyText(json, "application/json"),
          ),
        ),
      ),
      Effect.flatMap((response) => checkStatus(response, path)),
      Effect.flatMap(decodeResponse(schema)),
      Effect.retry(rateLimitSchedule),
    )
  }

  const postVoid = (
    path: string,
    body: unknown,
  ): Effect.Effect<void, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    return pipe(
      Effect.flatMap(
        Effect.tryPromise({
          try: () => Promise.resolve(JSON.stringify(body)),
          catch: () => new InvalidRequestError({ code: "SerializeFailed", message: "Failed to serialize request body", target: Option.none(), details: [] }),
        }),
        (json) => authorizeAndExecute(
          HttpClientRequest.post(url).pipe(
            HttpClientRequest.setHeader("Content-Type", "application/json"),
            HttpClientRequest.bodyText(json, "application/json"),
          ),
        ),
      ),
      Effect.flatMap((response) => {
        if (response.status >= 200 && response.status < 300) {
          return Effect.void
        }
        return handleErrorResponse(response, path)
      }),
      Effect.retry(rateLimitSchedule),
    )
  }

  const patch = <A, I>(
    path: string,
    body: unknown,
    schema: Schema.Schema<A, I>,
    headers?: Record<string, string>,
  ): Effect.Effect<A, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    return pipe(
      Effect.flatMap(
        Effect.tryPromise({
          try: () => Promise.resolve(JSON.stringify(body)),
          catch: () => new InvalidRequestError({ code: "SerializeFailed", message: "Failed to serialize request body", target: Option.none(), details: [] }),
        }),
        (json) => {
          const baseRequest = HttpClientRequest.patch(url).pipe(
            HttpClientRequest.setHeader("Content-Type", "application/json"),
            HttpClientRequest.bodyText(json, "application/json"),
          )
          const withExtraHeaders = headers
            ? Object.entries(headers).reduce(
                (r, [k, v]) => HttpClientRequest.setHeader(k, v)(r),
                baseRequest,
              )
            : baseRequest
          return authorizeAndExecute(withExtraHeaders)
        },
      ),
      Effect.flatMap((response) => checkStatus(response, path)),
      Effect.flatMap(decodeResponse(schema)),
      Effect.retry(rateLimitSchedule),
    )
  }

  const del = (
    path: string,
    headers?: Record<string, string>,
  ): Effect.Effect<void, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    const baseRequest = HttpClientRequest.del(url)
    const withExtraHeaders = headers
      ? Object.entries(headers).reduce(
          (r, [k, v]) => HttpClientRequest.setHeader(k, v)(r),
          baseRequest,
        )
      : baseRequest

    return pipe(
      authorizeAndExecute(withExtraHeaders),
      Effect.flatMap((response) => {
        if (response.status >= 200 && response.status < 300) {
          return Effect.void
        }
        return handleErrorResponse(response, path)
      }),
      Effect.retry(rateLimitSchedule),
    )
  }

  const stream = (
    path: string,
  ): Effect.Effect<Stream.Stream<Uint8Array, MsGraphError>, MsGraphError> => {
    const url = path.startsWith("https://") ? path : `${BASE_URL}${path}`
    return pipe(
      auth.acquireToken,
      Effect.flatMap((tokenInfo) =>
        pipe(
          HttpClientRequest.get(url),
          HttpClientRequest.setHeader("Authorization", `${tokenInfo.tokenType} ${tokenInfo.accessToken}`),
          httpClient.execute,
        ),
      ),
      Effect.mapError((error): MsGraphError => {
        if (error instanceof TokenExpiredError) return error
        return new TokenExpiredError({ expiredAt: Date.now() })
      }),
      Effect.flatMap((response) => {
        if (response.status >= 200 && response.status < 300) {
          const byteStream = pipe(
            response.stream,
            Stream.mapError((error): MsGraphError =>
              new InvalidRequestError({
                code: "StreamError",
                message: String(error),
                target: Option.some(path),
                details: [],
              }),
            ),
          )
          return Effect.succeed(byteStream)
        }
        return handleErrorResponse(response, path)
      }),
      Effect.scoped,
    )
  }

  return MsGraphHttpClient.of({ get, post, postVoid, patch, delete: del, stream })
}

export const MsGraphHttpClientLive = <F extends AuthFlow, P extends string>(flow: F) =>
  Layer.effect(
    MsGraphHttpClient,
    Effect.gen(function* () {
      const auth = yield* MsGraphAuthTag<F, P>(flow)
      const httpClient = yield* HttpClient.HttpClient
      return makeHttpClient<F, P>(auth, httpClient)
    }),
  )
