import { Effect, Match, Schedule } from "effect"
import type { MsGraphError } from "../Errors/errors"

const MAX_RETRIES = 3

const isRetryableError = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", () => true),
  Match.tag("ServiceUnavailable", () => true),
  Match.orElse(() => false),
)

export const rateLimitSchedule: Schedule.Schedule<number, MsGraphError, never, never> =
  Schedule.recurs(MAX_RETRIES).pipe(
    Schedule.while(({ input }) => isRetryableError(input as MsGraphError)),
  )

export const withRateLimit = <A, R>(
  effect: Effect.Effect<A, MsGraphError, R>,
): Effect.Effect<A, MsGraphError, R> =>
  Effect.retry(effect, rateLimitSchedule)
