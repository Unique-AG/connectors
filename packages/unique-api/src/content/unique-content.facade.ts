import { Content } from './content.dto';
import type { PublicSearchRequest, SearchResult } from './search-content.dto';

export interface GetContentByIdRequest {
  contentId: string;
}

export interface UniqueContentFacade {
  search(request: PublicSearchRequest): Promise<SearchResult>;
  getContentById(request: GetContentByIdRequest): Promise<Content>;
}
