import { describe, expect, it } from 'vitest';
import { isAllowedRedirectUri } from './redirect-uri';

describe('isAllowedRedirectUri', () => {
  it.each([
    'https://example.com/cb',
    'http://localhost:1234/cb',
    'http://127.0.0.1/cb',
    'http://[::1]/cb',
    'http://[::1]:8080/cb',
    'com.example.app:/cb',
    'cursor://anysphere.cursor-retrieval/oauth/callback',
    'vscode://vscode.github-authentication/callback',
  ])('accepts %s', (uri) => {
    expect(isAllowedRedirectUri(uri)).toBe(true);
  });

  it.each([
    'http://evil.example/cb',
    'http://localhost.evil.example/cb',
    'javascript:alert(1)',
    'data:text/html,hi',
    'file:///etc/passwd',
    'vbscript:x',
    'blob:https://example.com/id',
    'about:blank',
    'ftp://localhost/cb',
    'myapp:/cb',
    'https://example.com/cb#frag',
    'https://example.com/cb#',
    'not a url',
    '/relative/cb',
    '',
  ])('rejects %s', (uri) => {
    expect(isAllowedRedirectUri(uri)).toBe(false);
  });
});
