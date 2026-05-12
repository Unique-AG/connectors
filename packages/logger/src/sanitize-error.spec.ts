import { describe, expect, it } from 'vitest';
import { sanitizeError } from './sanitize-error';

describe('sanitizeError', () => {
  function createGraphqlClientError(
    baseMessage: string,
    variables: Record<string, unknown>,
  ): Error & { response: Record<string, unknown>; request: Record<string, unknown> } {
    const error = new Error(
      `${baseMessage}: ${JSON.stringify({
        response: { errors: [] },
        request: { variables },
      })}`,
    ) as Error & { response: Record<string, unknown>; request: Record<string, unknown> };
    error.response = {
      errors: [
        {
          message: baseMessage,
          path: ['contentUpsert', 'writeUrl'],
          extensions: { code: 'INTERNAL_SERVER_ERROR' },
        },
      ],
      status: 200,
    };
    error.request = { variables };
    return error;
  }

  it('serialises a plain Error', () => {
    const result = sanitizeError(new Error('Plain error')) as Record<string, unknown>;

    expect(result.message).toBe('Plain error');
    expect(result).not.toHaveProperty('graphqlErrors');
  });

  it('serialises a string thrown as error', () => {
    const result = sanitizeError('string error') as Record<string, unknown>;

    expect(result.message).toBe('string error');
  });

  it('strips raw variables from GraphQL client error message', () => {
    const error = createGraphqlClientError('Internal server error', {
      input: { title: 'Secret Report.docx', key: 'site-id/drive-id/item-id' },
      scopeId: 'scope-123',
    });

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.message).toBe('Internal server error');
    expect(JSON.stringify(result)).not.toContain('Secret Report.docx');
    expect(JSON.stringify(result)).not.toContain('site-id/drive-id/item-id');
    expect(JSON.stringify(result)).not.toContain('scope-123');
  });

  it('strips raw variables from GraphQL client error stack trace', () => {
    const error = createGraphqlClientError('Something failed', {
      input: { url: 'https://tenant.sharepoint.com/secret-path' },
    });

    const result = sanitizeError(error) as Record<string, unknown>;
    const stack = result.stack as string;

    expect(stack).not.toContain('secret-path');
    expect(stack).toContain('Something failed');
    expect(stack).toContain('at ');
  });

  it('treats GraphQL stack replacement text literally', () => {
    const error = createGraphqlClientError("Failed $& $' $`", {
      input: { token: 'secret-token' },
    });

    const result = sanitizeError(error);

    expect(result.stack).not.toContain('secret-token');
    expect(result.stack).toContain("Failed $& $' $`");
  });

  it('extracts structured graphqlErrors from GraphQL client error response', () => {
    const error = createGraphqlClientError('Internal server error', { input: {} });

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.graphqlErrors).toEqual([
      {
        message: 'Internal server error',
        path: ['contentUpsert', 'writeUrl'],
        code: 'INTERNAL_SERVER_ERROR',
      },
    ]);
    expect(result.statusCode).toBe(200);
  });

  it('handles GraphQL client error with no response errors array', () => {
    const error = createGraphqlClientError('Internal server error', {});
    delete error.response.errors;
    error.response.status = 500;

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.graphqlErrors).toBeUndefined();
    expect(result.statusCode).toBe(500);
  });

  it('sanitizes structurally matching GraphQL client errors', () => {
    const error = new Error(
      'Upstream failed: {"response":{"errors":[]},"request":{"variables":{"token":"secret-token"}}}',
    ) as Error & { response: Record<string, unknown>; request: Record<string, unknown> };
    error.response = {
      errors: [{ message: 'Upstream failed', path: ['query'], extensions: { code: 'FAILED' } }],
      status: 502,
    };
    error.request = { variables: { token: 'secret-token' } };

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.message).toBe('Upstream failed');
    expect(JSON.stringify(result)).not.toContain('secret-token');
    expect(result.graphqlErrors).toEqual([
      {
        message: 'Upstream failed',
        path: ['query'],
        code: 'FAILED',
      },
    ]);
    expect(result.statusCode).toBe(502);
  });

  it('does not treat non-ClientError with response/request as GraphQL error', () => {
    const error = new Error('boom') as Error & { response: object; request: object };
    error.response = { status: 500 };
    error.request = { query: 'query {}' };

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.message).toBe('boom');
    expect(result).not.toHaveProperty('graphqlErrors');
  });
});
