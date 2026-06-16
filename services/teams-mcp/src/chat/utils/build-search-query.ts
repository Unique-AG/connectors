/**
 * Parameters for assembling a KQL query string for the Microsoft Search API
 * (`POST /search/query`, entityType `chatMessage`).
 *
 * All fields are optional; the caller (the tool boundary) is responsible for
 * rejecting an all-empty set. Date fields are expected to already be validated
 * as ISO dates — only the date portion (`YYYY-MM-DD`) is used.
 */
export interface BuildSearchQueryParams {
  query?: string;
  from?: string;
  to?: string;
  /** User object id; dashes are stripped to match KQL identity syntax. */
  mentions?: string;
  /** ISO date/datetime; sliced to `YYYY-MM-DD`. */
  sentAfter?: string;
  /** ISO date/datetime; sliced to `YYYY-MM-DD`. */
  sentBefore?: string;
  hasAttachment?: boolean;
  isRead?: boolean;
  isMentioned?: boolean;
}

/**
 * Wraps a value in double quotes when it contains any character that could let
 * it smuggle a KQL operator into the query — whitespace, a quote, or one of the
 * property/comparison/grouping operators `: < > = ( )`. Without this, a single
 * token such as `sent>2020-01-01` (no whitespace, no colon) would be parsed as
 * a `sent>` property restriction rather than a literal search term. Embedded
 * quotes are escaped by doubling (`"` → `""`), per KQL string-literal rules.
 */
function quoteIfNeeded(value: string): string {
  if (/[\s:"<>=()]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/**
 * Assembles a KQL query string from structured search parameters.
 *
 * Free text comes first, followed by property restrictions. Returns `''` when
 * no parameter is set.
 */
export function buildSearchQuery(params: BuildSearchQueryParams): string {
  const fragments: string[] = [];

  if (params.query) {
    fragments.push(quoteIfNeeded(params.query));
  }
  if (params.from) {
    fragments.push(`from:${quoteIfNeeded(params.from)}`);
  }
  if (params.to) {
    fragments.push(`to:${quoteIfNeeded(params.to)}`);
  }
  if (params.mentions) {
    // Strip dashes to match KQL identity syntax, then quote like any other
    // value so a non-GUID value (e.g. `abc OR from:ceo`) cannot inject extra
    // restrictions.
    fragments.push(`mentions:${quoteIfNeeded(params.mentions.replace(/-/g, ''))}`);
  }
  if (params.sentAfter) {
    fragments.push(`sent>${params.sentAfter.slice(0, 10)}`);
  }
  if (params.sentBefore) {
    fragments.push(`sent<${params.sentBefore.slice(0, 10)}`);
  }
  // Booleans use exact KQL casing and are emitted whenever defined — `false`
  // is a meaningful restriction, so only `undefined` is omitted.
  if (params.hasAttachment !== undefined) {
    fragments.push(`hasAttachment:${params.hasAttachment}`);
  }
  if (params.isRead !== undefined) {
    fragments.push(`IsRead:${params.isRead}`);
  }
  if (params.isMentioned !== undefined) {
    fragments.push(`IsMentioned:${params.isMentioned}`);
  }

  return fragments.join(' ').trim();
}
