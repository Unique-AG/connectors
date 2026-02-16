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

const ENV_REF_PREFIX = 'os.environ/';

const envResolvableStringSchema = z.string().transform((val) => {
  if (!val.startsWith(ENV_REF_PREFIX)) return val;
  const varName = val.slice(ENV_REF_PREFIX.length);
  return process.env[varName] ?? '';
});

export const envResolvableRedactedStringSchema = envResolvableStringSchema
  .pipe(z.string().min(1))
  .transform((val) => new Redacted(val));

export const envResolvablePlainStringSchema = envResolvableStringSchema.pipe(z.string().min(1));
