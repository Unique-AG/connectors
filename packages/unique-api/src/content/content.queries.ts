import { gql } from 'graphql-request';
import { Content } from './content.dto';

export interface GetContentByIdQueryOutput {
  contentById: Content[];
}

export interface GetContentByIdQueryInput {
  contentIds: string[];
}

export const GET_CONTENT_BY_ID_QUERY = gql`
  query ContentById($contentIds: [String!]!) {
    contentById(contentIds: $contentIds) {
      id
      metadata
      title
      chunks {
          id
          startPage
          endPage
          order
          text
      }
    }
  }
`;
