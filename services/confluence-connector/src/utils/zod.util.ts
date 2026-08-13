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
  if (!val.startsWith(ENV_REF_PREFIX)) {
    return val;
  }
  const varName = val.slice(ENV_REF_PREFIX.length);
  return process.env[varName] ?? '';
});

// Secrets injected through Kubernetes secrets or `.env` files routinely carry a trailing newline,
// which is invisible in config but makes Confluence reject the credentials with a bare 401.
export const envRequiredSecretSchema = envResolvableStringSchema
  .pipe(z.string().trim().nonempty())
  .transform((val) => new Redacted(val));

export const envRequiredPlainSchema = envResolvableStringSchema.pipe(z.string().trim().nonempty());

export const redactedNonEmptyStringSchema = z
  .string()
  .trim()
  .nonempty()
  .transform((val) => new Redacted(val));
