import { Data, Option } from "effect"

export class AuthenticationFailedError extends Data.TaggedError("AuthenticationFailed")<{
  readonly reason:
    | "invalid_grant"
    | "invalid_client"
    | "interaction_required"
    | "expired_token"
    | "unknown"
  readonly message: string
  readonly correlationId: Option.Option<string>
}> {}

export class RateLimitedError extends Data.TaggedError("RateLimitedError")<{
  readonly retryAfter: number
  readonly resource: string
}> {}

export class InsufficientPermissionsError extends Data.TaggedError("InsufficientPermissions")<{
  readonly requiredScope: string
  readonly grantedScopes: ReadonlyArray<string>
}> {}

export class ResourceNotFoundError extends Data.TaggedError("ResourceNotFound")<{
  readonly resource: string
  readonly id: string
}> {}

export class QuotaExceededError extends Data.TaggedError("QuotaExceeded")<{
  readonly resource: string
  readonly limit: Option.Option<number>
}> {}

export class InvalidRequestError extends Data.TaggedError("InvalidRequest")<{
  readonly code: string
  readonly message: string
  readonly target: Option.Option<string>
  readonly details: ReadonlyArray<{ readonly code: string; readonly message: string }>
}> {}

export class TokenExpiredError extends Data.TaggedError("TokenExpired")<{
  readonly expiredAt: number
}> {}

export class ServiceUnavailableError extends Data.TaggedError("ServiceUnavailable")<{
  readonly retryAfter: Option.Option<number>
}> {}

export class BatchItemError extends Data.TaggedError("BatchItemError")<{
  readonly requestId: string
  readonly statusCode: number
  readonly inner: MsGraphError
}> {}

export type MsGraphError =
  | AuthenticationFailedError
  | RateLimitedError
  | InsufficientPermissionsError
  | ResourceNotFoundError
  | QuotaExceededError
  | InvalidRequestError
  | TokenExpiredError
  | ServiceUnavailableError
  | BatchItemError
