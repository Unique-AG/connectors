import { UriTemplate } from '@modelcontextprotocol/sdk/shared/uriTemplate.js';
import { filter, flatMap, map, pipe } from 'remeda';

/**
 * Matches a concrete `uri` against an RFC 6570 URI template and extracts captured values.
 *
 * Delegates path matching to the MCP SDK's built-in `UriTemplate.match()`, which supports all
 * RFC 6570 path operators: `{param}`, `{+param}` (reserved / cross-slash wildcard), etc.
 *
 * Query-string expressions (`{?a,b}`) are treated as optional: present query params are
 * extracted via `URLSearchParams` and merged into the result; absent ones are omitted.
 *
 * Returns a map of extracted parameter names to their string values, or `undefined` if the
 * URI path does not match the template.
 */
export function matchUriTemplate(template: string, uri: string): Record<string, string> | undefined {
  const [uriPath, uriQuery = ''] = uri.split('?');

  // Match path portion only — SDK match() treats {?query} params as required
  const pathTemplate = stripQueryExpressions(template);
  const pathResult = new UriTemplate(pathTemplate).match(uriPath);
  if (pathResult === null) return undefined;

  const params: Record<string, string> = Object.fromEntries(
    Object.entries(pathResult).map(([k, v]) => [k, Array.isArray(v) ? v.join(',') : v]),
  );

  if (uriQuery) {
    const queryParamNames = extractQueryParamNames(template);
    const searchParams = new URLSearchParams(uriQuery);
    for (const name of queryParamNames) {
      const value = searchParams.get(name);
      if (value !== null) {
        params[name] = value;
      }
    }
  }

  return params;
}

/**
 * Removes all `{?…}` query expressions from a URI template, leaving only path expressions.
 * Splits on `{?` and discards each expression up to and including the closing `}`.
 */
function stripQueryExpressions(template: string): string {
  const [first, ...rest] = template.split('{?');
  return [first, ...rest.map((s) => s.slice(s.indexOf('}') + 1))].join('');
}

/**
 * Extracts query parameter names declared in `{?a,b,c}` expressions within a URI template.
 */
function extractQueryParamNames(template: string): string[] {
  return pipe(
    template.split('{?').slice(1),
    flatMap((s) => s.slice(0, s.indexOf('}')).split(',')),
    map((p) => p.trim()),
    filter((p) => p.length > 0),
  );
}
