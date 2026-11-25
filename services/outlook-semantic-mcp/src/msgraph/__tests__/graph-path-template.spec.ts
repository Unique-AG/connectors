import { describe, expect, it } from 'vitest';
import { toGraphPathTemplate } from '../graph-path-template';

describe('toGraphPathTemplate', () => {
  it('drops the API version and the query string', () => {
    expect(toGraphPathTemplate('https://graph.microsoft.com/v1.0/me/messages?$top=1')).toBe(
      '/me/messages',
    );
  });

  it('replaces a mailbox address', () => {
    expect(
      toGraphPathTemplate(
        'https://graph.microsoft.com/v1.0/users/jane.doe@contoso.example/mailFolders',
      ),
    ).toBe('/users/:id/mailFolders');
  });

  it('replaces a percent-encoded mailbox address', () => {
    expect(
      toGraphPathTemplate(
        'https://graph.microsoft.com/v1.0/users/jane.doe%40contoso.example/messages',
      ),
    ).toBe('/users/:id/messages');
  });

  it('replaces Graph item ids and GUIDs', () => {
    expect(
      toGraphPathTemplate(
        'https://graph.microsoft.com/v1.0/users/0f8fad5b-d9cb-469f-a165-70867728950e/messages/AAMkAGI2THVSAAA=',
      ),
    ).toBe('/users/:id/messages/:id');
  });

  it('replaces a Graph item id without digits', () => {
    expect(
      toGraphPathTemplate('https://graph.microsoft.com/v1.0/me/messages/AAMkAGJhYWFhYWFhYWFhYQ=='),
    ).toBe('/me/messages/:id');
  });

  it('keeps dotted and $-prefixed Graph path words', () => {
    expect(
      toGraphPathTemplate(
        'https://graph.microsoft.com/v1.0/me/mailFolders/AAMkAGJhYWFhYWFhYWFhYQ==/messages/microsoft.graph.delta',
      ),
    ).toBe('/me/mailFolders/:id/messages/microsoft.graph.delta');
    expect(
      toGraphPathTemplate('https://graph.microsoft.com/v1.0/me/messages/AAMk1A==/$value'),
    ).toBe('/me/messages/:id/$value');
  });

  it('reads the URL of a Request', () => {
    expect(toGraphPathTemplate(new Request('https://graph.microsoft.com/v1.0/me/events'))).toBe(
      '/me/events',
    );
  });

  it('returns unknown for something that is not a URL', () => {
    expect(toGraphPathTemplate('not-a-url')).toBe('unknown');
  });
});
