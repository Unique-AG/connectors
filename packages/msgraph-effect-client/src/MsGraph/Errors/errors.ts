import { Schema } from "effect"

export class AuthenticationFailedError extends Schema.TaggedErrorClass<AuthenticationFailedError>()(
  "AuthenticationFailed",
  {
    reason: Schema.Union([
      Schema.Literal("invalid_grant"),
      Schema.Literal("invalid_client"),
      Schema.Literal("interaction_required"),
      Schema.Literal("expired_token"),
      Schema.Literal("unknown"),
    ]),
    message: Schema.String,
    correlationId: Schema.optionalKey(Schema.String),
  },
) {}

export class RateLimitedError extends Schema.TaggedErrorClass<RateLimitedError>()(
  "RateLimitedError",
  {
    retryAfter: Schema.Number,
    resource: Schema.String,
  },
) {}

export class InsufficientPermissionsError extends Schema.TaggedErrorClass<InsufficientPermissionsError>()(
  "InsufficientPermissions",
  {
    requiredScope: Schema.String,
    grantedScopes: Schema.Array(Schema.String),
  },
) {}

export class ResourceNotFoundError extends Schema.TaggedErrorClass<ResourceNotFoundError>()(
  "ResourceNotFound",
  {
    resource: Schema.String,
    id: Schema.String,
  },
) {}

export class QuotaExceededError extends Schema.TaggedErrorClass<QuotaExceededError>()(
  "QuotaExceeded",
  {
    resource: Schema.String,
    limit: Schema.optionalKey(Schema.Number),
  },
) {}

export class InvalidRequestError extends Schema.TaggedErrorClass<InvalidRequestError>()(
  "InvalidRequest",
  {
    code: Schema.String,
    message: Schema.String,
    target: Schema.optionalKey(Schema.String),
    details: Schema.Array(
      Schema.Struct({ code: Schema.String, message: Schema.String }),
    ),
  },
) {}

export class TokenExpiredError extends Schema.TaggedErrorClass<TokenExpiredError>()(
  "TokenExpired",
  {
    expiredAt: Schema.Number,
  },
) {}

export class ServiceUnavailableError extends Schema.TaggedErrorClass<ServiceUnavailableError>()(
  "ServiceUnavailable",
  {
    retryAfter: Schema.optionalKey(Schema.Number),
  },
) {}

export class BatchItemError extends Schema.TaggedErrorClass<BatchItemError>()(
  "BatchItemError",
  {
    requestId: Schema.String,
    statusCode: Schema.Number,
    inner: Schema.Any,
  },
) {}

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
