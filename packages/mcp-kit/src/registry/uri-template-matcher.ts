import { invariant } from '../errors/defect.js';

/** A literal string segment within a parsed URI template. */
type LiteralPart = { kind: 'literal'; value: string };

/** A variable segment within a parsed URI template. */
type ParamPart = {
  kind: 'param';
  /** Parameter name without trailing `*`. */
  name: string;
  /** When `true`, the parameter captures across `/` boundaries (`{param*}`). */
  wildcard: boolean;
};

type TemplatePart = LiteralPart | ParamPart;

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
  queryParams: string[],
): Record<string, string> | undefined {
  const [uriPath, uriQuery = ''] = uri.split('?');
  const parts = parseTemplateParts(stripQueryExpressions(template));
  const params = matchParts(parts, uriPath);
  if (!params) return undefined;

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

/**
 * Removes `{?…}` query expressions from a template string, leaving only path expressions.
 * Splits on `{?` and discards each expression up to and including the closing `}`.
 */
function stripQueryExpressions(template: string): string {
  const [first, ...rest] = template.split('{?');
  return [first, ...rest.map((s) => s.slice(s.indexOf('}') + 1))].join('');
}

/**
 * Splits a URI template path string into an ordered list of literal and parameter parts.
 * Splits on `{` to extract expressions; each expression is either `param` or `param*`.
 */
function parseTemplateParts(template: string): TemplatePart[] {
  const [firstLiteral, ...expressionSegments] = template.split('{');
  const parts: TemplatePart[] = [];

  if (firstLiteral) {
    parts.push({ kind: 'literal', value: firstLiteral });
  }

  for (const seg of expressionSegments) {
    const closingBrace = seg.indexOf('}');
    invariant(closingBrace !== -1, `Malformed URI template: missing closing brace in "${template}"`);

    const expr = seg.slice(0, closingBrace);
    const rest = seg.slice(closingBrace + 1);

    if (expr.endsWith('*')) {
      parts.push({ kind: 'param', name: expr.slice(0, -1), wildcard: true });
    } else {
      parts.push({ kind: 'param', name: expr, wildcard: false });
    }

    if (rest) {
      parts.push({ kind: 'literal', value: rest });
    }
  }

  return parts;
}

/**
 * Walks the template parts left-to-right consuming the URI string.
 * Literals must match exactly; params capture up to the next literal delimiter.
 * Simple params (`wildcard: false`) reject values that contain `/`.
 * Returns `undefined` on any mismatch or if the URI is not fully consumed.
 */
function matchParts(parts: TemplatePart[], uri: string): Record<string, string> | undefined {
  const params: Record<string, string> = {};
  let remaining = uri;

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];

    if (part.kind === 'literal') {
      if (!remaining.startsWith(part.value)) return undefined;
      remaining = remaining.slice(part.value.length);
      continue;
    }

    const nextLiteral = parts
      .slice(i + 1)
      .find((p): p is LiteralPart => p.kind === 'literal');

    const boundary = nextLiteral
      ? remaining.indexOf(nextLiteral.value)
      : remaining.length;

    if (boundary === -1 || boundary === 0) return undefined;

    const captured = remaining.slice(0, boundary);

    if (!part.wildcard && captured.includes('/')) return undefined;

    params[part.name] = captured;
    remaining = remaining.slice(boundary);
  }

  return remaining ? undefined : params;
}
