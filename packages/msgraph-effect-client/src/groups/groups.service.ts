import { Effect, ServiceMap } from 'effect';
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../errors/errors.js';
import type { ODataPageType, ODataParams } from '../schemas/odata.schema.js';
import type { User } from '../users/user.schema.js';
import type { Group } from './group.schema.js';

export class GroupsService extends ServiceMap.Service<
  GroupsService,
  {
    readonly list: (
      params?: ODataParams<Group>,
    ) => Effect.Effect<ODataPageType<Group>, RateLimitedError | InvalidRequestError>;

    readonly getById: (
      groupId: string,
    ) => Effect.Effect<Group, ResourceNotFoundError | RateLimitedError>;

    readonly listMembers: (
      groupId: string,
    ) => Effect.Effect<ODataPageType<User>, ResourceNotFoundError | RateLimitedError>;

    readonly addMember: (
      groupId: string,
      userId: string,
    ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError | InvalidRequestError>;

    readonly removeMember: (
      groupId: string,
      userId: string,
    ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>;
  }
>()('MsGraph/Groups/GroupsService') {}
