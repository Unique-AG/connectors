import { Match } from 'effect';
import type { MsGraphError } from './errors.js';
import { InvalidRequestError, RateLimitedError, ResourceNotFoundError } from './errors.js';

/** Narrows MsGraphError to RateLimitedError | InvalidRequestError */
export const toRateLimitOrInvalid = (_resource: string) =>
  Match.type<MsGraphError>().pipe(
    Match.tag('RateLimitedError', (e) => e),
    Match.tag('InvalidRequest', (e) => e),
    Match.orElse(
      (e) =>
        new InvalidRequestError({
          code: e._tag,
          message: 'Unexpected error',
          target: undefined,
          details: [],
        }),
    ),
  );

/** Narrows to ResourceNotFoundError | RateLimitedError */
export const toNotFoundOrRateLimit = (resource: string) =>
  Match.type<MsGraphError>().pipe(
    Match.tag('RateLimitedError', (e) => e),
    Match.tag('ResourceNotFound', (e) => e),
    Match.orElse(() => new ResourceNotFoundError({ resource, id: 'unknown' })),
  );

/** Narrows to RateLimitedError only */
export const toRateLimit = (resource: string) =>
  Match.type<MsGraphError>().pipe(
    Match.tag('RateLimitedError', (e) => e),
    Match.orElse(() => new RateLimitedError({ retryAfter: 0, resource })),
  );

/** Narrows to RateLimitedError | InvalidRequestError | ResourceNotFoundError */
export const toNotFoundRateLimitOrInvalid = (_resource: string) =>
  Match.type<MsGraphError>().pipe(
    Match.tag('RateLimitedError', (e) => e),
    Match.tag('ResourceNotFound', (e) => e),
    Match.tag('InvalidRequest', (e) => e),
    Match.orElse(
      (e) =>
        new InvalidRequestError({
          code: e._tag,
          message: 'Unexpected error',
          target: undefined,
          details: [],
        }),
    ),
  );
