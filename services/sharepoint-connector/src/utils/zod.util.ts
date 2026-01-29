import { z } from 'zod';
import { Redacted } from './redacted';

export const urlWithoutTrailingSlashSchema = (description: string, message: string) =>
  z
    .url()
    .describe(description)
    .refine((url) => !url.endsWith('/'), { message });

export const coercedPositiveIntSchema = z.coerce.number().int().positive();
export const coercedPositiveNumberSchema = z.coerce.number().positive();
export const requiredStringSchema = z.string().trim().min(1);

export const redactedStringSchema = z.string().transform((val) => new Redacted(val));
export const redactedNonEmptyStringSchema = z
  .string()
  .nonempty()
  .transform((val) => new Redacted(val));
export const redactedOptionalStringSchema = z
  .string()
  .optional()
  .transform((val) => (val ? new Redacted(val) : undefined));
