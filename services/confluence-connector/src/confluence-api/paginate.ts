import type { PaginatedResponse } from './types/confluence-api.types';

export async function paginateAll<T>(
  initialUrl: string,
  baseUrl: string,
  httpGet: <R>(url: string) => Promise<R>,
): Promise<T[]> {
  const results: T[] = [];
  let url: string | undefined = initialUrl;
  while (url) {
    const response: PaginatedResponse<T> = await httpGet(url);
    results.push(...response.results);
    url = response._links.next ? `${baseUrl}${response._links.next}` : undefined;
  }
  return results;
}
