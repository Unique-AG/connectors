import type { z } from 'zod';
import { paginatedResponseSchema } from './types/confluence-api.types';

export async function fetchAllPaginated<T>(
  initialUrl: string,
  baseUrl: string,
  httpGet: (url: string) => Promise<unknown>,
  itemSchema: z.ZodType<T>,
): Promise<T[]> {
  const schema = paginatedResponseSchema(itemSchema);
  const results: T[] = [];
  let url: string | undefined = initialUrl;

  while (url) {
    const rawRespose = await httpGet(url);
    const response = schema.parse(rawRespose);

    results.push(...response.results);
    url = response._links.next ? `${baseUrl}${response._links.next}` : undefined;
  }
  return results;
}
