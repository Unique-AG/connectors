import type { z } from 'zod';
import { paginatedResponseSchema } from './types/confluence-api.types';

export async function fetchAllPaginated<T extends z.ZodTypeAny>(
  initialUrl: string,
  baseUrl: string,
  httpGet: (url: string) => Promise<unknown>,
  itemSchema: T,
): Promise<z.infer<T>[]> {
  const schema = paginatedResponseSchema(itemSchema);
  const results: z.infer<T>[] = [];
  let url: string | undefined = initialUrl;
  while (url) {
    const raw = await httpGet(url);
    const response = schema.parse(raw);
    results.push(...response.results);
    url = response._links.next ? `${baseUrl}${response._links.next}` : undefined;
  }
  return results;
}
