import { Context, Effect } from "effect"
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { Group } from "../Schemas/Group"
import type { ODataPageType, ODataParams } from "../Schemas/OData"
import type { User } from "../Schemas/User"

export interface GroupsService {
  readonly list: (
    params?: ODataParams<Group>,
  ) => Effect.Effect<ODataPageType<Group>, RateLimitedError | InvalidRequestError>

  readonly getById: (
    groupId: string,
  ) => Effect.Effect<Group, ResourceNotFoundError | RateLimitedError>

  readonly listMembers: (
    groupId: string,
  ) => Effect.Effect<ODataPageType<User>, ResourceNotFoundError | RateLimitedError>

  readonly addMember: (
    groupId: string,
    userId: string,
  ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError | InvalidRequestError>

  readonly removeMember: (
    groupId: string,
    userId: string,
  ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>
}

export const GroupsService = Context.GenericTag<GroupsService>("MsGraph/GroupsService")
