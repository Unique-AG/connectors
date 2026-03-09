import assert from 'node:assert';
import { sanitizePath } from '@unique-ag/utils';
import { first } from 'remeda';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueHttpClient } from '../clients/unique-http.client';
import type { IngestionState } from '../ingestion/ingestion.types';
import { Content, ContentSchema } from './content.dto';
import {
  GET_CONTENT_BY_ID_QUERY,
  GetContentByIdQueryInput,
  GetContentByIdQueryOutput,
  STATISTICS_INGESTION_QUERY,
  StatisticsIngestionQueryInput,
  StatisticsIngestionQueryOutput,
} from './content.queries';
import { PublicSearchRequest, SearchResult, SearchResultSchema } from './search-content.dto';
import type { GetContentByIdRequest, UniqueContentFacade } from './unique-content.facade';
import { UniqueOwnerType } from '../types';

export class ContentService implements UniqueContentFacade {
  public constructor(
    private readonly httpClient: UniqueHttpClient,
    private readonly uniqueGraphqlClient: UniqueGraphqlClient,
    private readonly baseUrl: string,
  ) {}

  public async search(request: PublicSearchRequest): Promise<SearchResult> {
    const baseUrl = new URL(this.baseUrl);

    const { body } = await this.httpClient.request({
      method: 'POST',
      path: sanitizePath({
        path: `${baseUrl.pathname}/v1/search`,
        prefixWithSlash: true,
      }),
      body: JSON.stringify(request),
    });

    const responseData = await body.json();
    return SearchResultSchema.parse(responseData);
  }

  public async getContentById(request: GetContentByIdRequest): Promise<Content> {
    const result = await this.uniqueGraphqlClient.request<
      GetContentByIdQueryOutput,
      GetContentByIdQueryInput
    >(GET_CONTENT_BY_ID_QUERY, { contentIds: [request.contentId] });

    assert.ok(result?.contentById, 'Invalid response from Unique API');
    const item = first(result.contentById);
    assert.ok(item, 'Unique API Content not found');
    return ContentSchema.parse(item);
  }

  public async getIngestionStats(
    scopeId: string,
  ): Promise<Partial<Record<IngestionState, number>>> {
    const result = await this.uniqueGraphqlClient.request<
      StatisticsIngestionQueryOutput,
      StatisticsIngestionQueryInput
    >(STATISTICS_INGESTION_QUERY, {
      where: { ownerId: { equals: scopeId }, ownerType: { equals: UniqueOwnerType.Scope } },
    });

    assert.ok(result?.statisticsIngestion, 'Invalid response from Unique API statistics');
    return result?.statisticsIngestion.counts;
  }
}
