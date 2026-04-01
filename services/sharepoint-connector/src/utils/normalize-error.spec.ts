import { describe, expect, it } from 'vitest';
import { normalizeError, sanitizeError } from './normalize-error';

describe('normalizeError', () => {
  it('returns Error instances unchanged', () => {
    const error = new Error('Test error');
    const result = normalizeError(error);

    expect(result).toBe(error);
    expect(result.message).toBe('Test error');
  });

  it('converts string to Error', () => {
    const result = normalizeError('Something went wrong');

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('Something went wrong');
  });

  it('handles null', () => {
    const result = normalizeError(null);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('null');
  });

  it('handles undefined', () => {
    const result = normalizeError(undefined);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('undefined');
  });

  it('converts symbol to Error', () => {
    const sym = Symbol('test');
    const result = normalizeError(sym);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(sym.toString());
  });

  it('converts function to Error', () => {
    const fn = function testFunction() {};
    const result = normalizeError(fn);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toContain('testFunction');
  });

  it('converts plain object to JSON string', () => {
    const obj = { code: 'ERR_001', details: 'Something failed' };
    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(JSON.stringify(obj));
  });

  it('converts number to Error', () => {
    const result = normalizeError(404);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('404');
  });

  it('converts boolean to Error', () => {
    const result = normalizeError(false);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('false');
  });

  it('handles circular references', () => {
    const obj: Record<string, unknown> = { name: 'test' };
    obj.self = obj;

    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('[object Object]');
  });

  it('handles objects with custom toString', () => {
    const obj = {
      toString() {
        return 'Custom error representation';
      },
    };

    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('{}');
  });

  it('handles arrays', () => {
    const arr = [1, 2, 3];
    const result = normalizeError(arr);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(JSON.stringify(arr));
  });

  it('preserves Error subclass types', () => {
    class CustomError extends Error {
      public constructor(message: string) {
        super(message);
        this.name = 'CustomError';
      }
    }

    const error = new CustomError('Custom message');
    const result = normalizeError(error);

    expect(result).toBe(error);
    expect(result.name).toBe('CustomError');
  });
});

describe('sanitizeError', () => {
  function createGraphqlClientError(
    baseMessage: string,
    variables: Record<string, unknown>,
  ): Error & { response: object; request: object } {
    const response = {
      data: null,
      errors: [
        {
          message: 'Internal server error',
          path: ['contentUpsert', 'writeUrl'],
          extensions: { code: 'INTERNAL_SERVER_ERROR' },
        },
      ],
      status: 200,
    };
    const request = {
      query:
        'mutation ContentUpsert($input: ContentCreateInput!) { contentUpsert(input: $input) { id } }',
      variables,
    };
    const message = `${baseMessage}: ${JSON.stringify({ response, request })}`;
    const error = new Error(message) as Error & {
      response: typeof response;
      request: typeof request;
    };
    error.response = response;
    error.request = request;
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

  it('extracts structured graphqlErrors from GraphQL client error response', () => {
    const error = createGraphqlClientError('test', { input: {} });

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
    const error = new Error('msg') as Error & { response: object; request: object };
    error.response = { status: 500 };
    error.request = { query: 'query {}', variables: {} };

    const result = sanitizeError(error) as Record<string, unknown>;

    expect(result.graphqlErrors).toBeUndefined();
    expect(result.statusCode).toBe(500);
  });
});
