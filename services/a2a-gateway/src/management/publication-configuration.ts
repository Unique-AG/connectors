import { z } from 'zod';

const boundedString = (maximum: number) => z.string().trim().min(1).max(maximum);
const optionalHttpsUrl = z
  .url()
  .refine((value) => new URL(value).protocol === 'https:', 'URL must use HTTPS')
  .optional();

export const publicationSkillSchema = z.object({
  id: boundedString(100).regex(/^[a-zA-Z0-9._-]+$/),
  name: boundedString(100),
  description: boundedString(1_000),
  tags: z.array(boundedString(50)).max(20).default([]),
  examples: z.array(boundedString(500)).max(10).default([]),
});

export const publicationCardSchema = z.object({
  name: boundedString(100),
  description: boundedString(2_000),
  documentationUrl: optionalHttpsUrl,
  iconUrl: optionalHttpsUrl,
  provider: z
    .object({
      organization: boundedString(100),
      url: z.url().refine((value) => new URL(value).protocol === 'https:', 'URL must use HTTPS'),
    })
    .optional(),
});

export const publicationWriteSchema = z.object({
  enabled: z.boolean(),
  card: publicationCardSchema,
  skills: z.array(publicationSkillSchema).max(50).default([]),
});

export type PublicationCardConfiguration = z.infer<typeof publicationCardSchema>;
export type PublicationConfiguration = z.infer<typeof publicationWriteSchema>;
