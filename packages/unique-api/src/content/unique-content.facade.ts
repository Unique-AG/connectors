import { Content } from './content.dto';
import { GetContentByIdQueryInput } from './content.queries';
import type { PublicSearchRequest, SearchResult } from './search-content.dto';

export interface UniqueContentFacade {
  search(request: PublicSearchRequest): Promise<SearchResult>;
  getContentById(request: GetContentByIdQueryInput): Promise<Content>;
}
