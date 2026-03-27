import { Effect, Schedule, Duration } from "effect"
import type { MsGraphError, RateLimitedError, ServiceUnavailableError } from "../Errors/errors"

const MAX_RETRIES = 3

const baseExponential = Schedule.exponential(Duration.seconds(1), 2).pipe(
  Schedule.jittered,
  Schedule.upTo(Duration.seconds(60)),
  Schedule.compose(Schedule.recurs(MAX_RETRIES)),
)

const isRetryableError = (
  error: MsGraphError,
): error is RateLimitedError | ServiceUnavailableError =>
  error._tag === "RateLimitedError" || error._tag === "ServiceUnavailable"

export const rateLimitSchedule: Schedule.Schedule<number, MsGraphError, never> =
  Schedule.recurWhile(isRetryableError).pipe(
    Schedule.intersect(baseExponential),
    Schedule.map(([, output]) => output),
  )

export const withRateLimit = <A, R>(
  effect: Effect.Effect<A, MsGraphError, R>,
): Effect.Effect<A, MsGraphError, R> =>
  Effect.retry(effect, rateLimitSchedule)
