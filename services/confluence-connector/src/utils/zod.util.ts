import { z } from 'zod';
import { Redacted } from './redacted';

export const urlWithoutTrailingSlashSchema = (description: string, message: string) =>
  z
    .url()
    .describe(description)
    .refine((url) => !url.endsWith('/'), { message });

export const coercedPositiveIntSchema = z.coerce.number().int().positive();
export const coercedPositiveNumberSchema = z.coerce.number().positive();
export const requiredStringSchema = z.string().trim().nonempty();

const ENV_REF_PREFIX = 'os.environ/';

const envResolvableStringSchema = z.string().transform((val) => {
  if (!val.startsWith(ENV_REF_PREFIX)) return val;
  const varName = val.slice(ENV_REF_PREFIX.length);
  return process.env[varName] ?? '';
});

export const envRequiredSecretSchema = envResolvableStringSchema
  .pipe(z.string().nonempty())
  .transform((val) => new Redacted(val));

export const envRequiredPlainSchema = envResolvableStringSchema.pipe(z.string().nonempty());
