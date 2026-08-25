import { afterEach, describe, expect, it } from 'vitest';
import { ProxyConfigSchema } from '../proxy.config';

const USER_ENV = 'PROXY_CONFIG_SPEC_USERNAME';
const PASS_ENV = 'PROXY_CONFIG_SPEC_PASSWORD';

const baseBasicAuthInput = {
  authMode: 'username_password',
  host: 'proxy.example.com',
  port: 8080,
  protocol: 'http',
} as const;

describe('ProxyConfigSchema', () => {
  afterEach(() => {
    delete process.env[USER_ENV];
    delete process.env[PASS_ENV];
  });

  it('redacts an inline username and password', () => {
    const result = ProxyConfigSchema.parse({
      ...baseBasicAuthInput,
      username: 'alice',
      password: 's3cr3t',
    });

    if (result.authMode !== 'username_password') {
      throw new Error('expected username_password config');
    }

    expect(result.username.value).toBe('alice');
    expect(result.password.value).toBe('s3cr3t');
    expect(String(result.username)).toBe('[Redacted]');
    expect(String(result.password)).toBe('[Redacted]');
  });

  it('resolves os.environ/ prefixes for username and password', () => {
    process.env[USER_ENV] = 'resolved-user';
    process.env[PASS_ENV] = 'resolved-pass';

    const result = ProxyConfigSchema.parse({
      ...baseBasicAuthInput,
      username: `os.environ/${USER_ENV}`,
      password: `os.environ/${PASS_ENV}`,
    });

    if (result.authMode !== 'username_password') {
      throw new Error('expected username_password config');
    }

    expect(result.username.value).toBe('resolved-user');
    expect(result.password.value).toBe('resolved-pass');
    expect(String(result.username)).toBe('[Redacted]');
    expect(String(result.password)).toBe('[Redacted]');
  });

  it('strips the trailing newline a Kubernetes secret adds', () => {
    process.env[USER_ENV] = 'proxy-user\n';
    process.env[PASS_ENV] = 'sup3r-s3cret\n';

    const result = ProxyConfigSchema.parse({
      ...baseBasicAuthInput,
      username: `os.environ/${USER_ENV}`,
      password: `os.environ/${PASS_ENV}`,
    });

    if (result.authMode !== 'username_password') {
      throw new Error('expected username_password config');
    }

    expect(result.username.value).toBe('proxy-user');
    expect(result.password.value).toBe('sup3r-s3cret');
  });

  it('rejects a missing os.environ/ target', () => {
    expect(() =>
      ProxyConfigSchema.parse({
        ...baseBasicAuthInput,
        username: 'os.environ/PROXY_CONFIG_SPEC_MISSING',
        password: 's3cr3t',
      }),
    ).toThrow();
  });
});
