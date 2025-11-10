import { Injectable, Logger } from '@nestjs/common';
import { pick, prop } from 'remeda';
import { ScopeManagementClient } from '../clients/scope-management.client';
import {
  ADD_GROUP_MEMBERS_MUTATION,
  AddGroupMembersMutationInput,
  AddGroupMembersMutationResult,
  CREATE_GROUP_MUTATION,
  CreateGroupMutationInput,
  CreateGroupMutationResult,
  DELETE_GROUP_MUTATION,
  DeleteGroupMutationInput,
  DeleteGroupMutationResult,
  LIST_GROUPS_QUERY,
  ListGroupsQueryInput,
  ListGroupsQueryResult,
  REMOVE_GROUP_MEMBER_MUTATION,
  RemoveGroupMemberMutationInput,
  RemoveGroupMemberMutationResult,
  SHAREPOINT_CONNECTOR_GROUP_CREATED_BY,
  SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX,
  UPDATE_GROUP_MUTATION,
  UpdateGroupMutationInput,
  UpdateGroupMutationResult,
} from './unique-groups.consts';
import { UniqueGroup } from './unique-groups.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueGroupsService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(private readonly scopeManagementClient: ScopeManagementClient) {}

  public async listAllGroups(): Promise<UniqueGroup[]> {
    this.logger.log('Requesting all groups from Unique API');

    let skip = 0;
    const groups: UniqueGroup[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.get(
        async (client) =>
          await client.request<ListGroupsQueryResult, ListGroupsQueryInput>(LIST_GROUPS_QUERY, {
            externalIdPrefix: SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX,
            skip,
            take: BATCH_SIZE,
          }),
      );
      groups.push(
        ...batchResult.listGroups.map((group) => ({
          ...pick(group, ['id', 'name', 'externalId']),
          memberIds: group.members.map(prop('entityId')),
        })),
      );
      batchCount = batchResult.listGroups.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return groups;
  }

  public async createGroup(group: Omit<UniqueGroup, 'id' | 'memberIds'>): Promise<UniqueGroup> {
    const result = await this.scopeManagementClient.get(
      async (client) =>
        await client.request<CreateGroupMutationResult, CreateGroupMutationInput>(
          CREATE_GROUP_MUTATION,
          {
            name: group.name,
            externalId: group.externalId,
            createdBy: SHAREPOINT_CONNECTOR_GROUP_CREATED_BY,
          },
        ),
    );

    return {
      ...result.createGroup,
      memberIds: [],
    };
  }

  public async updateGroup(
    group: Omit<UniqueGroup, 'memberIds' | 'externalId'>,
  ): Promise<Omit<UniqueGroup, 'memberIds'>> {
    const result = await this.scopeManagementClient.get(
      async (client) =>
        await client.request<UpdateGroupMutationResult, UpdateGroupMutationInput>(
          UPDATE_GROUP_MUTATION,
          {
            groupId: group.id,
            name: group.name,
          },
        ),
    );

    return result.updateGroup;
  }

  public async deleteGroup(groupId: string): Promise<void> {
    await this.scopeManagementClient.get(
      async (client) =>
        await client.request<DeleteGroupMutationResult, DeleteGroupMutationInput>(
          DELETE_GROUP_MUTATION,
          {
            groupId,
          },
        ),
    );
  }

  public async addGroupMembers(groupId: string, memberIds: string[]): Promise<void> {
    await this.scopeManagementClient.get(
      async (client) =>
        await client.request<AddGroupMembersMutationResult, AddGroupMembersMutationInput>(
          ADD_GROUP_MEMBERS_MUTATION,
          {
            groupId,
            userIds: memberIds,
          },
        ),
    );
  }

  public async removeGroupMembers(groupId: string, userIds: string[]): Promise<void> {
    // It seems removal is done from the other side - you can remove single user from multiple
    // groups, so we need to remove each user from the group separately.
    for (const userId of userIds) {
      await this.scopeManagementClient.get(
        async (client) =>
          await client.request<RemoveGroupMemberMutationResult, RemoveGroupMemberMutationInput>(
            REMOVE_GROUP_MEMBER_MUTATION,
            {
              groupId,
              userId,
            },
          ),
      );
    }
  }
}
