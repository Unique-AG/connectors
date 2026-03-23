import { describe, expect, it } from 'vitest';
import { matchUriTemplate } from './uri-template-matcher';

describe('matchUriTemplate', () => {
  it('matches exact static URIs', () => {
    expect(matchUriTemplate('users://list', 'users://list')).toEqual({});
  });

  it('returns undefined for non-matching URI', () => {
    expect(matchUriTemplate('users://{id}', 'posts://123')).toBeUndefined();
  });

  it('returns undefined when path segments do not match', () => {
    expect(matchUriTemplate('users://{id}/profile', 'users://123/settings')).toBeUndefined();
  });

  it('extracts simple path params', () => {
    const result = matchUriTemplate('users://{user_id}/profile', 'users://abc-123/profile');
    expect(result).toEqual({ user_id: 'abc-123' });
  });

  it('extracts multiple simple path params', () => {
    const result = matchUriTemplate('orgs://{org}/repos/{repo}', 'orgs://acme/repos/my-repo');
    expect(result).toEqual({ org: 'acme', repo: 'my-repo' });
  });

  it('extracts wildcard path params spanning slashes via {+param}', () => {
    const result = matchUriTemplate('files://{+path}', 'files://a/b/c.txt');
    expect(result).toEqual({ path: 'a/b/c.txt' });
  });

  it('does not match when a required path segment is missing', () => {
    const result = matchUriTemplate('users://{id}', 'users://');
    expect(result).toBeUndefined();
  });

  it('matches URI with no template params (static match)', () => {
    const result = matchUriTemplate('config://app/settings', 'config://app/settings');
    expect(result).toEqual({});
  });

  it('does not match a longer URI against a shorter template', () => {
    const result = matchUriTemplate('users://{id}', 'users://123/extra');
    expect(result).toBeUndefined();
  });
});
