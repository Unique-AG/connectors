import { gql } from 'graphql-request';

export interface ListUsersQueryInput {
  skip: number;
  take: number;
  where?: {
    active?: {
      equals: boolean;
    };
  };
}

export interface ListUsersQueryResult {
  listUsers: {
    totalCount: number;
    nodes: {
      id: string;
      active: boolean;
      email: string;
    }[];
  };
}

export const LIST_USERS_QUERY = gql`
  query ListUsers($skip: Int!, $take: Int!, $where: UserWhereInput) {
    listUsers: paginatedUsers(skip: $skip, take: $take, where: $where) {
      totalCount
      nodes {
        id
        active
        email
      }
    }
  }
`;

export interface GetCurrentUserQueryResult {
  me: {
    user: {
      id: string;
    };
  };
}

export const GET_CURRENT_USER_QUERY = gql`
  query User {
    me {
      user {
        id
      }
    }
  }
`;
