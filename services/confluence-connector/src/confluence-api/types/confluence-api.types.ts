export enum ContentType {
  PAGE = 'page',
  FOLDER = 'folder',
  DATABASE = 'database',
}

export interface ConfluencePage {
  id: string;
  title: string;
  type: ContentType;
  space: { id: string; key: string; name: string };
  body?: { storage: { value: string } };
  version: { when: string };
  _links: { webui: string };
  metadata: { labels: { results: Array<{ name: string }> } };
}

export interface PaginatedResponse<T> {
  results: T[];
  _links: { next?: string };
}
