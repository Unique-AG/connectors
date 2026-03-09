import { gql } from 'graphql-request';
import type { IngestionState } from '../ingestion/ingestion.types';
import { Content } from './content.dto';
import { UniqueOwnerType } from '../types';

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

interface StatisticsIngestionQueryCondition {
  ownerId: { equals: string };
  ownerType: { equals: UniqueOwnerType };
}

export interface StatisticsIngestionQueryInput {
  where: StatisticsIngestionQueryCondition;
}

export interface StatisticsIngestionQueryOutput {
  statisticsIngestion: { counts: Record<IngestionState, number> };
}

export const STATISTICS_INGESTION_QUERY = gql`
  query StatisticsIngestion($where: StatisticsIngestionWhereInput!) {
    statisticsIngestion(where: $where) {
      counts
    }
  }
`;
