import { Duration, Effect, Schedule } from "effect"
import type { MsGraphError, RateLimitedError, ServiceUnavailableError } from "../Errors/errors"

const MAX_RETRIES = 3

const isRetryableError = (
  error: MsGraphError,
): error is RateLimitedError | ServiceUnavailableError =>
  error._tag === "RateLimitedError" || error._tag === "ServiceUnavailable"

const baseExponential: Schedule.Schedule<Duration.Duration, unknown, never, never> =
  Schedule.exponential(Duration.seconds(1), 2).pipe(Schedule.jittered)

export const rateLimitSchedule: Schedule.Schedule<number, MsGraphError, never, never> =
  Schedule.recurs(MAX_RETRIES).pipe(
    Schedule.while(({ input }) => isRetryableError(input as MsGraphError)),
  )

export const withRateLimit = <A, R>(
  effect: Effect.Effect<A, MsGraphError, R>,
): Effect.Effect<A, MsGraphError, R> =>
  Effect.retry(effect, rateLimitSchedule)
