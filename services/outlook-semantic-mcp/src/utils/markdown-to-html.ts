import MarkdownIt from 'markdown-it';

// html: false escapes raw HTML in the input so the model cannot inject
// <script>, event handlers, or other tags directly. markdown-it's default
// validateLink also blocks javascript:, vbscript:, file:, and data: URLs
// (except safe image data URIs), so [x](javascript:...) is neutralized.
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
});

export function markdownToHtml(markdown: string): string {
  return md.render(markdown);
}
