import { describe, expect, it } from 'vitest';
import { matchUriTemplate } from './uri-template-matcher';

describe('matchUriTemplate', () => {
  it('matches exact static URIs', () => {
    expect(matchUriTemplate('users://list', 'users://list', [], [])).toEqual({});
  });

  it('returns undefined for non-matching URI', () => {
    expect(matchUriTemplate('users://{id}', 'posts://123', ['id'], [])).toBeUndefined();
  });

  it('returns undefined when path segments do not match', () => {
    expect(matchUriTemplate('users://{id}/profile', 'users://123/settings', ['id'], [])).toBeUndefined();
  });

  it('extracts simple path params', () => {
    const result = matchUriTemplate('users://{user_id}/profile', 'users://abc-123/profile', ['user_id'], []);
    expect(result).toEqual({ user_id: 'abc-123' });
  });

  it('extracts multiple simple path params', () => {
    const result = matchUriTemplate('orgs://{org}/repos/{repo}', 'orgs://acme/repos/my-repo', ['org', 'repo'], []);
    expect(result).toEqual({ org: 'acme', repo: 'my-repo' });
  });

  it('extracts wildcard path params', () => {
    const result = matchUriTemplate('files://{path*}', 'files://a/b/c.txt', ['path*'], []);
    expect(result).toEqual({ path: 'a/b/c.txt' });
  });

  it('extracts query params', () => {
    const result = matchUriTemplate(
      'data://{id}{?format,limit}',
      'data://123?format=json&limit=10',
      ['id'],
      ['format', 'limit'],
    );
    expect(result).toEqual({ id: '123', format: 'json', limit: '10' });
  });

  it('handles omitted optional query params', () => {
    const result = matchUriTemplate('data://{id}{?format}', 'data://123', ['id'], ['format']);
    expect(result).toEqual({ id: '123' });
  });

  it('handles partially supplied query params', () => {
    const result = matchUriTemplate(
      'data://{id}{?format,limit}',
      'data://456?limit=5',
      ['id'],
      ['format', 'limit'],
    );
    expect(result).toEqual({ id: '456', limit: '5' });
  });

  it('does not match when a required path segment is missing', () => {
    const result = matchUriTemplate('users://{id}', 'users://', ['id'], []);
    expect(result).toBeUndefined();
  });

  it('matches URI with no template params (static match)', () => {
    const result = matchUriTemplate('config://app/settings', 'config://app/settings', [], []);
    expect(result).toEqual({});
  });

  it('does not match a longer URI against a shorter template', () => {
    const result = matchUriTemplate('users://{id}', 'users://123/extra', ['id'], []);
    expect(result).toBeUndefined();
  });
});
