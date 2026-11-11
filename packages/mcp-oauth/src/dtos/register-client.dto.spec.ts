import { describe, expect, it } from 'vitest';
import { RegisterClientSchema } from './register-client.dto';

const parse = (redirectUris: string[]) =>
  RegisterClientSchema.safeParse({ client_name: 'test', redirect_uris: redirectUris });

describe('RegisterClientSchema redirect_uris', () => {
  it('accepts https and loopback http URIs', () => {
    const result = parse(['https://example.com/cb', 'http://localhost:1234/cb', 'http://[::1]/cb']);

    expect(result.success).toBe(true);
  });

  it.each([
    'http://evil.example/cb',
    'javascript:alert(1)',
    'data:text/html,x',
    'file:///etc/passwd',
    'https://x/cb#frag',
  ])('rejects %s with invalid_redirect_uri', (uri) => {
    const result = parse([uri]);

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toContain('invalid_redirect_uri');
  });

  it('rejects an empty array', () => {
    expect(parse([]).success).toBe(false);
  });
});
