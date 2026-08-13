import { afterEach, describe, expect, it } from 'vitest';
import {
  envRequiredPlainSchema,
  envRequiredSecretSchema,
  redactedNonEmptyStringSchema,
} from '../zod.util';

const ENV_VAR = 'ZOD_UTIL_SPEC_SECRET';

describe('credential schemas', () => {
  afterEach(() => {
    delete process.env[ENV_VAR];
  });

  it('strips the trailing newline a Kubernetes secret adds to a password', () => {
    process.env[ENV_VAR] = 'sup3r-s3cret\n';

    const password = envRequiredSecretSchema.parse(`os.environ/${ENV_VAR}`);

    expect(password.value).toBe('sup3r-s3cret');
  });

  it('strips surrounding whitespace from an inline secret', () => {
    expect(envRequiredSecretSchema.parse('  sup3r-s3cret  ').value).toBe('sup3r-s3cret');
    expect(envRequiredPlainSchema.parse('  plain-value\n')).toBe('plain-value');
    expect(redactedNonEmptyStringSchema.parse(' proxy-pass\n').value).toBe('proxy-pass');
  });

  it('rejects a whitespace-only secret', () => {
    expect(() => envRequiredSecretSchema.parse('   ')).toThrow();
  });
});
