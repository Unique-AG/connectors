import { Effect, Result, Schema } from "effect"
import {
  InsufficientPermissionsError,
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
  ServiceUnavailableError,
  TokenExpiredError,
  type MsGraphError,
} from "./errors"

const ODataErrorSchema = Schema.Struct({
  error: Schema.Struct({
    code: Schema.String,
    message: Schema.String,
    target: Schema.optional(Schema.String),
    details: Schema.optional(
      Schema.Array(
        Schema.Struct({
          code: Schema.String,
          message: Schema.String,
        }),
      ),
    ),
  }),
})

type ODataError = Schema.Schema.Type<typeof ODataErrorSchema>

const parseRetryAfter = (headers: Record<string, string | undefined>): number => {
  const retryAfter = headers["retry-after"] ?? headers["Retry-After"]
  if (!retryAfter) return 30
  const parsed = Number(retryAfter)
  return Number.isNaN(parsed) ? 30 : parsed
}

const parseODataBody = (
  body: unknown,
): ODataError["error"] | null => {
  const result = Schema.decodeUnknownResult(ODataErrorSchema)(body)
  if (Result.isSuccess(result)) {
    return result.success.error
  }
  return null
}

export const decodeGraphError = (
  statusCode: number,
  body: unknown,
  headers: Record<string, string | undefined>,
  resource = "unknown",
): MsGraphError => {
  const odataError = parseODataBody(body)

  switch (statusCode) {
    case 401:
      return new TokenExpiredError({
        expiredAt: Date.now(),
      })

    case 403:
      return new InsufficientPermissionsError({
        requiredScope: odataError?.code ?? "unknown",
        grantedScopes: [],
      })

    case 404:
      return new ResourceNotFoundError({
        resource,
        id: odataError?.message ?? "unknown",
      })

    case 429:
      return new RateLimitedError({
        retryAfter: parseRetryAfter(headers),
        resource,
      })

    case 503: {
      const retryAfterHeader = headers["retry-after"] ?? headers["Retry-After"]
      const retryAfterSeconds = retryAfterHeader ? Number(retryAfterHeader) : undefined
      return new ServiceUnavailableError({
        retryAfter: retryAfterSeconds !== undefined && !Number.isNaN(retryAfterSeconds)
          ? retryAfterSeconds
          : undefined,
      })
    }

    default:
      return new InvalidRequestError({
        code: odataError?.code ?? `HTTP_${statusCode}`,
        message: odataError?.message ?? `Request failed with status ${statusCode}`,
        target: odataError?.target ?? undefined,
        details: odataError?.details ?? [],
      })
  }
}

export const decodeGraphErrorEffect = (
  statusCode: number,
  body: unknown,
  headers: Record<string, string | undefined>,
  resource = "unknown",
): Effect.Effect<never, MsGraphError> =>
  Effect.fail(decodeGraphError(statusCode, body, headers, resource))

export const mapResponseToError = <E>(
  statusCode: number,
  getBody: Effect.Effect<unknown, E>,
  headers: Record<string, string | undefined>,
  resource = "unknown",
): Effect.Effect<never, MsGraphError | E> =>
  Effect.flatMap(getBody, (body) =>
    decodeGraphErrorEffect(statusCode, body, headers, resource),
  )
