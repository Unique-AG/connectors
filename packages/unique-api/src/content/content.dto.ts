import { z } from 'zod/v4';

export const ChunkSchema = z.object({
  id: z.string(),
  startPage: z.number().nullable(),
  endPage: z.number().nullable(),
  order: z.number().nullable(),
  text: z.string(),
});

export const ContentSchema = z.object({
  id: z.string(),
  key: z.string(),
  title: z.string().nullable(),
  metadata: z.unknown().nullable(),
  chunks: z.array(ChunkSchema).optional(),
});

export type Content = z.infer<typeof ContentSchema>;
