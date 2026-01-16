import { z } from 'zod';

export const urlWithoutTrailingSlashSchema = (description: string, message: string) =>
  z
    .url()
    .describe(description)
    .refine((url) => !url.endsWith('/'), { message });

export const coercedPositiveIntSchema = z.coerce.number().int().positive();
export const requiredStringSchema = z.string().min(1);
