import { Logger } from '@nestjs/common';
import { pick, prop } from 'remeda';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueApiGroups } from '../types';
import {
  ADD_GROUP_MEMBERS_MUTATION,
  type AddGroupMembersMutationInput,
  type AddGroupMembersMutationResult,
  CREATE_GROUP_MUTATION,
  type CreateGroupMutationInput,
  type CreateGroupMutationResult,
  DELETE_GROUP_MUTATION,
  type DeleteGroupMutationInput,
  type DeleteGroupMutationResult,
  getListGroupsQuery,
  type ListGroupsQueryInput,
  type ListGroupsQueryResult,
  REMOVE_GROUP_MEMBER_MUTATION,
  type RemoveGroupMemberMutationInput,
  type RemoveGroupMemberMutationResult,
  UPDATE_GROUP_MUTATION,
  type UpdateGroupMutationInput,
  type UpdateGroupMutationResult,
} from './groups.queries';
import type { Group, GroupWithMembers } from './groups.types';

export class GroupsService implements UniqueApiGroups {
  public constructor(
    private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly logger: Logger,
    private readonly options: { defaultBatchSize: number },
  ) {}

  public async listByExternalIdPrefix(externalIdPrefix: string): Promise<GroupWithMembers[]> {
    this.logger.log(
      `[ExternalIdPrefix: ${externalIdPrefix}] Requesting all groups from Unique API`,
    );

    let skip = 0;
    const groups: GroupWithMembers[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.request<
        ListGroupsQueryResult<true>,
        ListGroupsQueryInput
      >(getListGroupsQuery(true), {
        where: {
          externalId: {
            startsWith: externalIdPrefix,
          },
        },
        skip,
        take: this.options.defaultBatchSize,
      });
      groups.push(
        ...batchResult.listGroups.map((group) => ({
          ...pick(group, ['id', 'name', 'externalId']),
          memberIds: group.members.map(prop('entityId')),
        })),
      );
      batchCount = batchResult.listGroups.length;
      skip += this.options.defaultBatchSize;
    } while (batchCount === this.options.defaultBatchSize);

    return groups;
  }

  public async create(group: {
    name: string;
    externalId: string;
    createdBy: string;
  }): Promise<GroupWithMembers> {
    const result = await this.scopeManagementClient.request<
      CreateGroupMutationResult,
      CreateGroupMutationInput
    >(CREATE_GROUP_MUTATION, {
      name: group.name,
      externalId: group.externalId,
      createdBy: group.createdBy,
    });

    return {
      ...result.createGroup,
      memberIds: [],
    };
  }

  public async update(group: { id: string; name: string }): Promise<Group> {
    const result = await this.scopeManagementClient.request<
      UpdateGroupMutationResult,
      UpdateGroupMutationInput
    >(UPDATE_GROUP_MUTATION, {
      groupId: group.id,
      name: group.name,
    });

    return result.updateGroup;
  }

  public async delete(groupId: string): Promise<void> {
    await this.scopeManagementClient.request<DeleteGroupMutationResult, DeleteGroupMutationInput>(
      DELETE_GROUP_MUTATION,
      { groupId },
    );
  }

  public async addMembers(groupId: string, memberIds: string[]): Promise<void> {
    await this.scopeManagementClient.request<
      AddGroupMembersMutationResult,
      AddGroupMembersMutationInput
    >(ADD_GROUP_MEMBERS_MUTATION, {
      groupId,
      userIds: memberIds,
    });
  }

  public async removeMembers(groupId: string, userIds: string[]): Promise<void> {
    for (const userId of userIds) {
      await this.scopeManagementClient.request<
        RemoveGroupMemberMutationResult,
        RemoveGroupMemberMutationInput
      >(REMOVE_GROUP_MEMBER_MUTATION, {
        groupId,
        userId,
      });
    }
  }
}
