import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { pick, prop } from 'remeda';
import { Config } from '../../config';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { SCOPE_MANAGEMENT_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
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
  getListGroupsQuery,
  ListGroupsQueryInput,
  ListGroupsQueryResult,
  REMOVE_GROUP_MEMBER_MUTATION,
  RemoveGroupMemberMutationInput,
  RemoveGroupMemberMutationResult,
  SHAREPOINT_CONNECTOR_GROUP_CREATED_BY,
  UPDATE_GROUP_MUTATION,
  UpdateGroupMutationInput,
  UpdateGroupMutationResult,
} from './unique-groups.consts';
import { UniqueGroup, UniqueGroupWithMembers } from './unique-groups.types';
import { getSharepointConnectorGroupExternalIdPrefix } from './unique-groups.utils';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueGroupsService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    @Inject(SCOPE_MANAGEMENT_CLIENT) private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async listAllGroupsForSite(siteId: string): Promise<UniqueGroupWithMembers[]> {
    const logPrefix = `[SiteId: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    this.logger.log(`${logPrefix} Requesting all groups from Unique API`);

    let skip = 0;
    const groups: UniqueGroupWithMembers[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.get(
        async (client) =>
          await client.request<ListGroupsQueryResult<true>, ListGroupsQueryInput>(
            getListGroupsQuery(true),
            {
              where: {
                externalId: {
                  startsWith: getSharepointConnectorGroupExternalIdPrefix(siteId),
                },
              },
              skip,
              take: BATCH_SIZE,
            },
          ),
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

  public async getRootGroup(): Promise<UniqueGroup | null> {
    this.logger.log('Requesting root group from Unique API');

    const result = await this.scopeManagementClient.get(
      async (client) =>
        await client.request<ListGroupsQueryResult<false>, ListGroupsQueryInput>(
          getListGroupsQuery(false),
          {
            skip: 0,
            take: 1,
            where: {
              name: {
                equals: 'Root Group',
              },
            },
          },
        ),
    );

    return result.listGroups[0] ?? null;
  }

  public async createGroup(
    group: Omit<UniqueGroupWithMembers, 'id' | 'memberIds'>,
  ): Promise<UniqueGroupWithMembers> {
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
    group: Omit<UniqueGroupWithMembers, 'memberIds' | 'externalId'>,
  ): Promise<Omit<UniqueGroupWithMembers, 'memberIds'>> {
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
