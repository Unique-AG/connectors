import { Effect, ServiceMap, Stream } from 'effect';
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../errors/errors.js';
import type { ODataPageType, ODataParams } from '../schemas/odata.schema.js';
import type { User } from './user.schema.js';

export class UsersService extends ServiceMap.Service<
  UsersService,
  {
    readonly list: (
      params?: ODataParams<User>,
    ) => Effect.Effect<ODataPageType<User>, RateLimitedError | InvalidRequestError>;

    readonly getById: (
      id: string,
      params?: Pick<ODataParams<User>, '$select' | '$expand'>,
    ) => Effect.Effect<User, ResourceNotFoundError | RateLimitedError>;

    readonly me: (
      params?: Pick<ODataParams<User>, '$select' | '$expand'>,
    ) => Effect.Effect<User, RateLimitedError>;

    readonly listDirectReports: (
      userId: string,
      params?: ODataParams<User>,
    ) => Effect.Effect<ODataPageType<User>, ResourceNotFoundError | RateLimitedError>;

    readonly getManager: (
      userId: string,
    ) => Effect.Effect<User, ResourceNotFoundError | RateLimitedError>;

    readonly getPhoto: (
      userId: string,
    ) => Effect.Effect<Stream.Stream<Uint8Array, RateLimitedError>, ResourceNotFoundError>;
  }
>()('MsGraph/Users/UsersService') {}
