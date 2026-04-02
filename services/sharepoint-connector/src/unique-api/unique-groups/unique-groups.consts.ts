import { gql } from 'graphql-request';
import type { VariableLogPolicy } from '../../utils/sanitize-graphql-variables';

export const SHAREPOINT_CONNECTOR_GROUP_CREATED_BY = 'sharepoint-connector';

export interface ListGroupsQueryInput {
  where: {
    externalId?: {
      startsWith: string;
    };
    name?: {
      equals: string;
    };
  };
  skip: number;
  take: number;
}

interface ListGroupsQueryResultNode {
  id: string;
  name: string;
  externalId: string;
}

interface ListGroupsQueryResultNodeWithMembers extends ListGroupsQueryResultNode {
  members: { entityId: string }[];
}

export interface ListGroupsQueryResult<TWithMembers extends boolean> {
  listGroups: TWithMembers extends true
    ? ListGroupsQueryResultNodeWithMembers[]
    : ListGroupsQueryResultNode[];
}

export const LIST_GROUPS_LOG_SAFE_KEYS: VariableLogPolicy = ['skip', 'take'];

export function getListGroupsQuery(includeMembers: boolean): string {
  const membersFields = includeMembers
    ? `members {
        entityId
      }`
    : '';

  return gql`
    query ListGroups($where: GroupWhereInput!, $skip: Int!, $take: Int!) {
      listGroups: allGroups(where: $where, skip: $skip, take: $take) {
        id
        name
        externalId
        ${membersFields}
      }
    }
  `;
}

export interface CreateGroupMutationInput {
  name: string;
  externalId: string;
  createdBy: string;
}

export interface CreateGroupMutationResult {
  createGroup: {
    id: string;
    name: string;
    externalId: string;
  };
}

export const CREATE_GROUP_LOG_SAFE_KEYS: VariableLogPolicy = ['createdBy'];

export const CREATE_GROUP_MUTATION = gql`
  mutation CreateGroup($name: String!, $externalId: String!, $createdBy: String!) {
    createGroup(input: { name: $name, externalId: $externalId, createdBy: $createdBy }) {
      id
      name
      externalId
    }
  }
`;

export interface UpdateGroupMutationInput {
  groupId: string;
  name: string;
}

export interface UpdateGroupMutationResult {
  updateGroup: {
    id: string;
    name: string;
    externalId: string;
  };
}

export const UPDATE_GROUP_LOG_SAFE_KEYS: VariableLogPolicy = ['groupId'];

export const UPDATE_GROUP_MUTATION = gql`
  mutation UpdateGroup($groupId: String!, $name: String!) {
    updateGroup(id: $groupId, input: { name: $name }) {
      id
      name
      externalId
    }
  }
`;

export interface DeleteGroupMutationInput {
  groupId: string;
}

export interface DeleteGroupMutationResult {
  deleteGroup: {
    id: string;
  };
}

export const DELETE_GROUP_LOG_SAFE_KEYS: VariableLogPolicy = ['groupId'];

export const DELETE_GROUP_MUTATION = gql`
  mutation DeleteGroup($groupId: String!) {
    deleteGroup(id: $groupId) {
      id
    }
  }
`;

export interface AddGroupMembersMutationInput {
  groupId: string;
  userIds: string[];
}

export interface AddGroupMembersMutationResult {
  addGroupMembers: {
    entityId: string;
    groupId: string;
  }[];
}

export const ADD_GROUP_MEMBERS_LOG_SAFE_KEYS: VariableLogPolicy = ['groupId'];

export const ADD_GROUP_MEMBERS_MUTATION = gql`
  mutation AddGroupMembers($groupId: String!, $userIds: [String!]!) {
    addGroupMembers: createMemberships(groupId: $groupId, userIds: $userIds) {
      entityId
      groupId
    }
  }
`;

export interface RemoveGroupMemberMutationInput {
  groupId: string;
  userId: string;
}

export type RemoveGroupMemberMutationResult = boolean;

export const REMOVE_GROUP_MEMBER_LOG_SAFE_KEYS: VariableLogPolicy = ['groupId'];

export const REMOVE_GROUP_MEMBER_MUTATION = gql`
  mutation RemoveGroupMember($groupId: String!, $userId: String!) {
    removeGroupMember: deleteMemberships(groupIds: [$groupId], userId: $userId)
  }
`;
