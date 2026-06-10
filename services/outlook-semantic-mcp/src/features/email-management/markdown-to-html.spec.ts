import { describe, expect, it } from 'vitest';
import { markdownToHtml } from './markdown-to-html';

describe('markdownToHtml', () => {
  it('renders paragraphs and inline formatting', () => {
    const html = markdownToHtml('Hello **world**\n\nSecond paragraph.');

    expect(html).toContain('<strong>world</strong>');
    expect(html).toContain('<p>');
  });

  it('renders unordered and ordered lists', () => {
    const html = markdownToHtml('- one\n- two\n\n1. first\n2. second');

    expect(html).toContain('<ul>');
    expect(html).toContain('<li>one</li>');
    expect(html).toContain('<ol>');
    expect(html).toContain('<li>first</li>');
  });

  it('renders links', () => {
    const html = markdownToHtml('[unique](https://unique.ai)');

    expect(html).toContain('<a href="https://unique.ai">unique</a>');
  });

  it('converts single newlines inside a paragraph to <br>', () => {
    const html = markdownToHtml('line one\nline two');

    expect(html).toContain('<br>');
  });

  it('escapes raw HTML tags instead of passing them through', () => {
    const html = markdownToHtml('<script>alert(1)</script>');

    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('escapes raw HTML with inline event handlers so no executable tag is emitted', () => {
    const html = markdownToHtml('<img src=x onerror="alert(1)">');

    expect(html).not.toMatch(/<img[\s>]/i);
    expect(html).toContain('&lt;img');
  });

  it('does not render <a> tags for javascript: links', () => {
    const html = markdownToHtml('[click](javascript:alert(1))');

    expect(html).not.toMatch(/<a\b/i);
    expect(html).not.toMatch(/href\s*=/i);
  });

  it('does not render <a> tags for vbscript: links', () => {
    const html = markdownToHtml('[click](vbscript:msgbox(1))');

    expect(html).not.toMatch(/<a\b/i);
    expect(html).not.toMatch(/href\s*=/i);
  });

  it('does not render <a> tags for data: links', () => {
    const html = markdownToHtml('[click](data:text/html,<script>alert(1)</script>)');

    expect(html).not.toMatch(/<a\b/i);
    expect(html).not.toMatch(/href\s*=/i);
  });
});
