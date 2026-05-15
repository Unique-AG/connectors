import { describe, expect, it } from 'vitest';
import { createRedactRequestSerializer } from './redact-request-serializer';

describe('createRedactRequestSerializer', () => {
  const apiKey = 'secret-api-key';

  it('replaces the api-key in req.url with [Redacted]', () => {
    const redact = createRedactRequestSerializer(apiKey);

    const result = redact({ url: `/${apiKey}/mcp`, method: 'POST' });

    expect(result.url).toBe('/[Redacted]/mcp');
  });

  it('replaces every occurrence of the api-key in req.url', () => {
    const redact = createRedactRequestSerializer(apiKey);

    const result = redact({ url: `/${apiKey}/mcp?next=/${apiKey}/mcp` });

    expect(result.url).toBe('/[Redacted]/mcp?next=/[Redacted]/mcp');
  });

  it('preserves all other fields produced by the default serializer', () => {
    const redact = createRedactRequestSerializer(apiKey);
    const input = {
      id: 'req-1',
      method: 'POST',
      url: `/${apiKey}/mcp`,
      headers: { 'content-type': 'application/json' },
      remoteAddress: '127.0.0.1',
      remotePort: 54321,
    };

    const result = redact(input);

    expect(result).toEqual({
      id: 'req-1',
      method: 'POST',
      url: '/[Redacted]/mcp',
      headers: { 'content-type': 'application/json' },
      remoteAddress: '127.0.0.1',
      remotePort: 54321,
    });
  });

  it('returns the request unchanged when the api-key is empty', () => {
    const redact = createRedactRequestSerializer('');
    const input = { url: '/some/path', method: 'GET' };

    const result = redact(input);

    expect(result).toBe(input);
  });

  it('returns the request unchanged when req.url is missing', () => {
    const redact = createRedactRequestSerializer(apiKey);
    const input = { method: 'GET', headers: {} };

    const result = redact(input);

    expect(result).toBe(input);
  });

  it('does not mutate the input object', () => {
    const redact = createRedactRequestSerializer(apiKey);
    const input = { url: `/${apiKey}/mcp` };

    redact(input);

    expect(input.url).toBe(`/${apiKey}/mcp`);
  });
});
