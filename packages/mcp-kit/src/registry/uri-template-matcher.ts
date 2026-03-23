import { UriTemplate } from '@modelcontextprotocol/sdk/shared/uriTemplate.js';

/**
 * Matches a concrete `uri` against an RFC 6570 URI template and extracts captured values.
 *
 * Delegates entirely to the MCP SDK's built-in `UriTemplate.match()`.
 * Supports `{param}` (simple segment) and `{+param}` (cross-slash wildcard).
 *
 * Returns a map of extracted parameter names to their string values, or `undefined`
 * if the URI does not match the template.
 */
export function matchUriTemplate(template: string, uri: string): Record<string, string> | undefined {
  const result = new UriTemplate(template).match(uri);
  if (result === null) return undefined;
  return Object.fromEntries(
    Object.entries(result).map(([k, v]) => [k, Array.isArray(v) ? v.join(',') : v]),
  );
}
