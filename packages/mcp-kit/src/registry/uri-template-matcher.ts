import { invariant } from '../errors/defect.js';

/**
 * Matches a concrete `uri` against a URI template and extracts captured values.
 *
 * Supported template syntax:
 * - `{param}` — simple segment, captures everything up to the next `/`
 * - `{param*}` — wildcard segment, captures across `/` boundaries
 * - `{?query,params}` — query-string parameters extracted from `uri`'s search string
 *
 * Returns a map of extracted parameter names to their decoded string values, or `undefined`
 * if the URI does not match the template's path.
 */
export function matchUriTemplate(
  template: string,
  uri: string,
  templateParams: string[],
  queryParams: string[],
): Record<string, string> | undefined {
  const [uriPath, uriQuery = ''] = uri.split('?');
  const templateWithoutQuery = template.replace(/\{\?[^}]+\}/g, '');

  let regexStr = escapeRegex(templateWithoutQuery);

  // Replace {param*} (wildcard - captures everything including /)
  regexStr = regexStr.replace(/\\\{(\w+)\\\*\\\}/g, '(?<$1>.+)');

  // Replace {param} (simple - captures up to next / or end)
  regexStr = regexStr.replace(/\\\{(\w+)\\\}/g, '(?<$1>[^/]+)');

  const regex = new RegExp(`^${regexStr}$`);
  const match = regex.exec(uriPath);
  if (!match) return undefined;

  const params: Record<string, string> = {};

  if (templateParams.length > 0) {
    invariant(match.groups !== undefined, 'Compiled URI template regex must have named capture groups');

    for (const param of templateParams) {
      const paramName = param.endsWith('*') ? param.slice(0, -1) : param;
      const value = match.groups[paramName];
      if (value !== undefined) {
        params[paramName] = value;
      }
    }
  }

  if (queryParams.length > 0 && uriQuery) {
    const searchParams = new URLSearchParams(uriQuery);
    for (const qParam of queryParams) {
      const value = searchParams.get(qParam);
      if (value !== null) {
        params[qParam] = value;
      }
    }
  }

  return params;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
