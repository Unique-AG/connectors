import { Context, Effect, Stream } from "effect"
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { ODataParams, ODataPageType } from "../Schemas/OData"
import type { User } from "../Schemas/User"

export interface UsersService {
  readonly list: (
    params?: ODataParams<User>,
  ) => Effect.Effect<ODataPageType<User>, RateLimitedError | InvalidRequestError>

  readonly getById: (
    id: string,
    params?: Pick<ODataParams<User>, "$select" | "$expand">,
  ) => Effect.Effect<User, ResourceNotFoundError | RateLimitedError>

  readonly me: (
    params?: Pick<ODataParams<User>, "$select" | "$expand">,
  ) => Effect.Effect<User, RateLimitedError>

  readonly listDirectReports: (
    userId: string,
    params?: ODataParams<User>,
  ) => Effect.Effect<ODataPageType<User>, ResourceNotFoundError | RateLimitedError>

  readonly getManager: (
    userId: string,
  ) => Effect.Effect<User, ResourceNotFoundError | RateLimitedError>

  readonly getPhoto: (
    userId: string,
  ) => Effect.Effect<Stream.Stream<Uint8Array, RateLimitedError>, ResourceNotFoundError>
}

export const UsersService = Context.GenericTag<UsersService>("MsGraph/UsersService")
