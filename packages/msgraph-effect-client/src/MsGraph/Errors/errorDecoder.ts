import { Effect, Match, Result, Schema } from 'effect';
import {
  InsufficientPermissionsError,
  InvalidRequestError,
  type MsGraphError,
  RateLimitedError,
  ResourceNotFoundError,
  ServiceUnavailableError,
  TokenExpiredError,
} from './errors';

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
});

type ODataError = Schema.Schema.Type<typeof ODataErrorSchema>;

const parseRetryAfter = (headers: Record<string, string | undefined>): number => {
  const retryAfter = headers['retry-after'] ?? headers['Retry-After'];
  if (!retryAfter) {
    return 30;
  }
  const parsed = Number(retryAfter);
  return Number.isNaN(parsed) ? 30 : parsed;
};

const parseODataBody = (body: unknown): ODataError['error'] | null =>
  Schema.decodeUnknownResult(ODataErrorSchema)(body).pipe(
    Result.match({
      onSuccess: (r) => r.error,
      onFailure: () => null,
    }),
  );

export const decodeGraphError = (
  statusCode: number,
  body: unknown,
  headers: Record<string, string | undefined>,
  resource = 'unknown',
): MsGraphError => {
  const odataError = parseODataBody(body);

  return Match.value(statusCode).pipe(
    Match.when(
      401,
      () =>
        new TokenExpiredError({
          expiredAt: Date.now(),
        }),
    ),
    Match.when(
      403,
      () =>
        new InsufficientPermissionsError({
          requiredScope: odataError?.code ?? 'unknown',
          grantedScopes: [],
        }),
    ),
    Match.when(
      404,
      () =>
        new ResourceNotFoundError({
          resource,
          id: odataError?.message ?? 'unknown',
        }),
    ),
    Match.when(
      429,
      () =>
        new RateLimitedError({
          retryAfter: parseRetryAfter(headers),
          resource,
        }),
    ),
    Match.when(503, () => {
      const retryAfterHeader = headers['retry-after'] ?? headers['Retry-After'];
      const retryAfterSeconds = retryAfterHeader ? Number(retryAfterHeader) : undefined;
      return new ServiceUnavailableError({
        retryAfter:
          retryAfterSeconds !== undefined && !Number.isNaN(retryAfterSeconds)
            ? retryAfterSeconds
            : undefined,
      });
    }),
    Match.orElse(
      () =>
        new InvalidRequestError({
          code: odataError?.code ?? `HTTP_${statusCode}`,
          message: odataError?.message ?? `Request failed with status ${statusCode}`,
          target: odataError?.target ?? undefined,
          details: odataError?.details ?? [],
        }),
    ),
  );
};

export const decodeGraphErrorEffect = Effect.fn('decodeGraphErrorEffect')(function* (
  statusCode: number,
  body: unknown,
  headers: Record<string, string | undefined>,
  resource = 'unknown',
): Effect.fn.Return<never, MsGraphError> {
  return yield* Effect.fail(decodeGraphError(statusCode, body, headers, resource));
});

export const mapResponseToError = <E>(
  statusCode: number,
  getBody: Effect.Effect<unknown, E>,
  headers: Record<string, string | undefined>,
  resource = 'unknown',
): Effect.Effect<never, MsGraphError | E> =>
  Effect.flatMap(getBody, (body) => decodeGraphErrorEffect(statusCode, body, headers, resource));
