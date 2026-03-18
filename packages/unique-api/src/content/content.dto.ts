import { Readable } from 'node:stream';
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
  title: z.string().nullable(),
  metadata: z.unknown().nullable(),
  chunks: z.array(ChunkSchema).optional(),
});

export type Content = z.infer<typeof ContentSchema>;

export interface DownloadedContent {
  data: Buffer;
  filename: string;
  mimeType: string;
}

export interface StreamedContent {
  stream: Readable;
  filename: string;
  mimeType: string;
  /** Total byte size from Content-Length header; undefined if the server did not provide it. */
  size: number | undefined;
}
