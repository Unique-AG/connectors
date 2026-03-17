import assert from 'node:assert';
import { sanitizePath } from '@unique-ag/utils';
import { first, isNullish } from 'remeda';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueHttpClient } from '../clients/unique-http.client';
import { Content, ContentSchema, DownloadedContent } from './content.dto';
import {
  GET_CONTENT_BY_ID_QUERY,
  GetContentByIdQueryInput,
  GetContentByIdQueryOutput,
} from './content.queries';
import { PublicSearchRequest, SearchResult, SearchResultSchema } from './search-content.dto';
import type { GetContentByIdRequest, UniqueContentFacade } from './unique-content.facade';

export class ContentService implements UniqueContentFacade {
  public constructor(
    private readonly httpClient: UniqueHttpClient,
    private readonly uniqueGraphqlClient: UniqueGraphqlClient,
    private readonly baseUrl: string,
  ) {}

  public async search(request: PublicSearchRequest): Promise<SearchResult> {
    const baseUrl = new URL(this.baseUrl);

    if (isNullish(request.scopeIds)) {
      // After the file based access migration not passing the scope ids results in empty search
      // because the scopeIds is defaulted to empty array in our search adapters which makes the query
      // return empty results.
      request.scopeIds = null;
    }

    const { body } = await this.httpClient.request({
      method: 'POST',
      path: sanitizePath({
        path: `${baseUrl.pathname}/v1/search/combinedSearch`,
        prefixWithSlash: true,
      }),
      body: JSON.stringify(request),
    });

    const responseData = await body.json();
    return SearchResultSchema.parse(responseData);
  }

  public async downloadContentById(contentId: string): Promise<DownloadedContent> {
    const baseUrl = new URL(this.baseUrl);

    const result = await this.httpClient.request({
      method: 'GET',
      path: sanitizePath({
        path: `${baseUrl.pathname}/v1/content/${encodeURIComponent(contentId)}/file`,
        prefixWithSlash: true,
      }),
    });

    const data = Buffer.from(await result.body.arrayBuffer());

    const contentDisposition = result.headers['content-disposition'];
    const filenameMatch =
      typeof contentDisposition === 'string'
        ? contentDisposition.match(/filename="?([^";]+)"?/)
        : null;
    const filename = filenameMatch ? filenameMatch[1] : contentId;

    const contentType = result.headers['content-type'];
    const mimeType =
      typeof contentType === 'string'
        ? contentType.split(';')[0].trim()
        : 'application/octet-stream';

    return { data, filename, mimeType };
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
}
