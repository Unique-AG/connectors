export interface ListUsersQueryInput {
  skip: number;
  take: number;
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

export const LIST_USERS_QUERY = `
  query ListUsers($skip: Int!, $take: Int!) {
    listUsers: paginatedUsers(skip: $skip, take: $take) {
      totalCount
      nodes {
        id
        active
        email
      }
    }
  }
`;
