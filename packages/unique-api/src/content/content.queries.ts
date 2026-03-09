import { gql } from 'graphql-request';
import type { IngestionState } from '../ingestion/ingestion.types';
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

export interface StatisticsIngestionQueryInput {
  scopePath: string;
}

export interface StatisticsIngestionItem {
  state: IngestionState;
  count: number;
}

export interface StatisticsIngestionQueryOutput {
  statisticsIngestion: StatisticsIngestionItem[];
}

export const STATISTICS_INGESTION_QUERY = gql`
  query StatisticsIngestion($scopePath: String!) {
    statisticsIngestion(scopePath: $scopePath) {
      state
      count
    }
  }
`;
