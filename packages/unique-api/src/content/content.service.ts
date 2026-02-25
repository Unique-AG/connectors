import assert from 'node:assert';
import { sanitizePath } from '@unique-ag/utils';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueHttpClient } from '../clients/unique-http.client';
import { Content, ContentSchema } from './content.dto';
import {
  GET_CONTENT_BY_ID_QUERY,
  GetContentByIdQueryInput,
  GetContentByIdQueryOutput,
} from './content.queries';
import { PublicSearchRequest, SearchResult, SearchResultSchema } from './search-content.dto';
import type { UniqueContentFacade } from './unique-content.facade';

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

  public async getContentById(request: GetContentByIdQueryInput): Promise<Content> {
    const result = await this.uniqueGraphqlClient.request<
      GetContentByIdQueryOutput,
      GetContentByIdQueryInput
    >(GET_CONTENT_BY_ID_QUERY, request);

    assert.ok(result?.getContentById, 'Invalid response from Unique API');
    return ContentSchema.parse(result.getContentById);
  }
}
