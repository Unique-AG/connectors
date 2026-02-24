import { z } from 'zod';

export enum ContentType {
  PAGE = 'page',
  FOLDER = 'folder',
  DATABASE = 'database',
  BLOGPOST = 'blogpost',
  WHITEBOARD = 'whiteboard',
  EMBED = 'embed',
}

export const confluencePageSchema = z.object({
  id: z.string(),
  title: z.string(),
  type: z.enum(ContentType),
  space: z.object({
    id: z.coerce.string(),
    key: z.string(),
    name: z.string(),
  }),
  body: z
    .object({
      storage: z.object({
        value: z.string(),
      }),
    })
    .optional(),
  version: z.object({
    when: z.string(),
  }),
  _links: z.object({
    webui: z.string(),
  }),
  metadata: z.object({
    labels: z.object({
      results: z.array(z.object({ name: z.string() })),
    }),
  }),
});

export type ConfluencePage = z.infer<typeof confluencePageSchema>;

export const paginatedResponseSchema = <T extends z.ZodTypeAny>(itemSchema: T) =>
  z.object({
    results: z.array(itemSchema),
    _links: z.object({
      next: z.string().optional(),
    }),
  });

export type PaginatedResponse<T> = {
  results: T[];
  _links: { next?: string };
};
