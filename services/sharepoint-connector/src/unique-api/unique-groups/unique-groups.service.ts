import { Inject, Injectable, Logger } from '@nestjs/common';
import { pick, prop } from 'remeda';
import { Smeared } from '../../utils/smeared';
import { SCOPE_MANAGEMENT_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  ADD_GROUP_MEMBERS_LOG_SAFE_KEYS,
  ADD_GROUP_MEMBERS_MUTATION,
  AddGroupMembersMutationInput,
  AddGroupMembersMutationResult,
  CREATE_GROUP_LOG_SAFE_KEYS,
  CREATE_GROUP_MUTATION,
  CreateGroupMutationInput,
  CreateGroupMutationResult,
  DELETE_GROUP_LOG_SAFE_KEYS,
  DELETE_GROUP_MUTATION,
  DeleteGroupMutationInput,
  DeleteGroupMutationResult,
  getListGroupsQuery,
  LIST_GROUPS_LOG_SAFE_KEYS,
  ListGroupsQueryInput,
  ListGroupsQueryResult,
  REMOVE_GROUP_MEMBER_LOG_SAFE_KEYS,
  REMOVE_GROUP_MEMBER_MUTATION,
  RemoveGroupMemberMutationInput,
  RemoveGroupMemberMutationResult,
  SHAREPOINT_CONNECTOR_GROUP_CREATED_BY,
  UPDATE_GROUP_LOG_SAFE_KEYS,
  UPDATE_GROUP_MUTATION,
  UpdateGroupMutationInput,
  UpdateGroupMutationResult,
} from './unique-groups.consts';
import { UniqueGroupWithMembers } from './unique-groups.types';
import { getSharepointConnectorGroupExternalIdPrefix } from './unique-groups.utils';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueGroupsService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(SCOPE_MANAGEMENT_CLIENT) private readonly scopeManagementClient: UniqueGraphqlClient,
  ) {}

  public async listAllGroupsForSite(siteId: Smeared): Promise<UniqueGroupWithMembers[]> {
    const logPrefix = `[Site: ${siteId}]`;
    const groupExternalIdPrefix = getSharepointConnectorGroupExternalIdPrefix(siteId.value);
    this.logger.log(`${logPrefix} Requesting all groups from Unique API`);

    let skip = 0;
    const groups: UniqueGroupWithMembers[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.request<
        ListGroupsQueryResult<true>,
        ListGroupsQueryInput
      >(
        getListGroupsQuery(true),
        {
          where: {
            externalId: {
              startsWith: groupExternalIdPrefix,
            },
          },
          skip,
          take: BATCH_SIZE,
        },
        { logSafeKeys: LIST_GROUPS_LOG_SAFE_KEYS },
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

  public async createGroup(
    group: Omit<UniqueGroupWithMembers, 'id' | 'memberIds'>,
  ): Promise<UniqueGroupWithMembers> {
    const result = await this.scopeManagementClient.request<
      CreateGroupMutationResult,
      CreateGroupMutationInput
    >(
      CREATE_GROUP_MUTATION,
      {
        name: group.name,
        externalId: group.externalId,
        createdBy: SHAREPOINT_CONNECTOR_GROUP_CREATED_BY,
      },
      { logSafeKeys: CREATE_GROUP_LOG_SAFE_KEYS },
    );

    return {
      ...result.createGroup,
      memberIds: [],
    };
  }

  public async updateGroup(
    group: Omit<UniqueGroupWithMembers, 'memberIds' | 'externalId'>,
  ): Promise<Omit<UniqueGroupWithMembers, 'memberIds'>> {
    const result = await this.scopeManagementClient.request<
      UpdateGroupMutationResult,
      UpdateGroupMutationInput
    >(
      UPDATE_GROUP_MUTATION,
      {
        groupId: group.id,
        name: group.name,
      },
      { logSafeKeys: UPDATE_GROUP_LOG_SAFE_KEYS },
    );

    return result.updateGroup;
  }

  public async deleteGroup(groupId: string): Promise<void> {
    await this.scopeManagementClient.request<DeleteGroupMutationResult, DeleteGroupMutationInput>(
      DELETE_GROUP_MUTATION,
      {
        groupId,
      },
      { logSafeKeys: DELETE_GROUP_LOG_SAFE_KEYS },
    );
  }

  public async addGroupMembers(groupId: string, memberIds: string[]): Promise<void> {
    await this.scopeManagementClient.request<
      AddGroupMembersMutationResult,
      AddGroupMembersMutationInput
    >(
      ADD_GROUP_MEMBERS_MUTATION,
      {
        groupId,
        userIds: memberIds,
      },
      { logSafeKeys: ADD_GROUP_MEMBERS_LOG_SAFE_KEYS },
    );
  }

  public async removeGroupMembers(groupId: string, userIds: string[]): Promise<void> {
    // It seems removal is done from the other side - you can remove single user from multiple
    // groups, so we need to remove each user from the group separately.
    for (const userId of userIds) {
      await this.scopeManagementClient.request<
        RemoveGroupMemberMutationResult,
        RemoveGroupMemberMutationInput
      >(
        REMOVE_GROUP_MEMBER_MUTATION,
        {
          groupId,
          userId,
        },
        { logSafeKeys: REMOVE_GROUP_MEMBER_LOG_SAFE_KEYS },
      );
    }
  }
}
