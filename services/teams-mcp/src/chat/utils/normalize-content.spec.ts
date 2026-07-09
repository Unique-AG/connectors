import { describe, expect, it } from 'vitest';
import { normalizeContent } from './normalize-content';

describe('normalizeContent', () => {
  it('returns text content unchanged', () => {
    expect(normalizeContent('hello world', 'text')).toBe('hello world');
  });

  it('strips HTML formatting while keeping the text', () => {
    expect(normalizeContent('<p>hello <strong>world</strong></p>', 'html')).toBe('hello world');
  });

  it('renders an inline image as [image] instead of dropping it', () => {
    const content =
      '<div><span><img height="63" src="https://graph.microsoft.com/v1.0/chats/x/messages/y/hostedContents/z/$value" width="67"></span></div>';
    expect(normalizeContent(content, 'html')).toBe('[image]');
  });

  it('keeps surrounding text alongside an image', () => {
    expect(normalizeContent('<p>look at this <img src="x"></p>', 'html')).toBe(
      'look at this [image]',
    );
  });

  it('renders a named attachment as [attachment: name]', () => {
    const content = '<attachment id="abc"></attachment>';
    expect(normalizeContent(content, 'html', [{ id: 'abc', name: 'report.pdf' }])).toBe(
      '[attachment: report.pdf]',
    );
  });

  it('falls back to [no text content] for an otherwise-empty body (not [deleted])', () => {
    expect(normalizeContent('<div></div>', 'html')).toBe('[no text content]');
  });

  it('returns [deleted] only when deletedDateTime is set', () => {
    expect(normalizeContent('anything', 'html', [], '2026-07-09T00:00:00Z')).toBe('[deleted]');
  });

  it('prefers the deletion tombstone over rendering content', () => {
    expect(normalizeContent('<p>still here</p>', 'html', [], '2026-07-09T00:00:00Z')).toBe(
      '[deleted]',
    );
  });

  it('detects adaptive card JSON blobs as [card]', () => {
    expect(normalizeContent('{"type":"AdaptiveCard","version":"1.0"}', 'html')).toBe('[card]');
  });
});
