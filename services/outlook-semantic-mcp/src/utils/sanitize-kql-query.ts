import { clampToValidDate } from '~/utils/clamp-to-valid-date';

const SUPPORTED_KQL_PROPERTIES = new Set([
  'attachment',
  'bcc',
  'body',
  'category',
  'cc',
  'from',
  'hasattachment',
  'hasattachments', // both spellings appear in MS docs
  'importance',
  'kind',
  'participants',
  'received',
  'recipients',
  'sent',
  'size',
  'subject',
  'to',
]);

const BOOLEAN_OP_RE = /^(?:AND|OR|NOT)$/;

/**
 * Wraps each KQL clause in double quotes and inserts an explicit AND between
 * adjacent clauses that have no boolean operator between them. The output is
 * ready to pass directly as the $search value on the /messages endpoint.
 *
 * Input forms handled:
 *   property:value              → "property:value"
 *   property:"phrase value"     → "property:phrase value"
 *   property:'phrase value'     → "property:phrase value"
 *   "already quoted"            → "already quoted"  (unchanged)
 *   free text words             → "free text words"  (accumulated into a phrase)
 *   AND / OR / NOT              → kept as-is between clauses
 */
function quoteKqlClauses(kql: string): string {
  if (!kql) {
    return kql;
  }

  // Order matters: more specific alternatives must come before more general ones.
  // Created fresh each call so the g-flag lastIndex is always 0.
  const TOKEN_RE = /"[^"]*"|\w+:"[^"]*"|\w+:'[^']*'|\w+:[^\s"']+|\b(?:AND|OR|NOT)\b|\S+/g;

  const parts: string[] = [];
  const freeText: string[] = [];
  let lastWasClause = false;

  const pushClause = (clause: string) => {
    if (lastWasClause) {
      parts.push('AND');
    }
    parts.push(clause);
    lastWasClause = true;
  };

  const flushFreeText = () => {
    if (freeText.length) {
      pushClause(`"${freeText.join(' ')}"`);
      freeText.length = 0;
    }
  };

  for (const [token] of kql.matchAll(TOKEN_RE)) {
    if (BOOLEAN_OP_RE.test(token)) {
      flushFreeText();
      parts.push(token);
      lastWasClause = false;
    } else if (token.startsWith('"')) {
      // Already double-quoted — pass through as-is.
      flushFreeText();
      pushClause(token);
    } else if (/^\w+:"[^"]*"$/.test(token)) {
      // property:"quoted value" → "property:quoted value"
      flushFreeText();
      const colonIdx = token.indexOf(':');
      pushClause(`"${token.slice(0, colonIdx)}:${token.slice(colonIdx + 2, -1)}"`);
    } else if (/^\w+:'[^']*'$/.test(token)) {
      // property:'quoted value' → "property:quoted value"
      flushFreeText();
      const colonIdx = token.indexOf(':');
      pushClause(`"${token.slice(0, colonIdx)}:${token.slice(colonIdx + 2, -1)}"`);
    } else if (/^\w+:[^\s"']+$/.test(token)) {
      // property:value → "property:value"
      flushFreeText();
      pushClause(`"${token}"`);
    } else {
      // Bare free-text word — accumulate into a single quoted phrase.
      freeText.push(token);
    }
  }

  flushFreeText();
  return parts.join(' ');
}

export function sanitizeKqlQuery(kql: string): string {
  const sanitized = kql
    // Normalize Unicode smart/curly quotes to ASCII (LLMs sometimes emit these)
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    // Uppercase boolean operators — KQL requires AND/OR/NOT in uppercase.
    // The alternation skips content inside double-quoted phrases so that
    // subject:"budget and planning" is not mangled into subject:"budget AND planning".
    .replace(/"[^"]*"|\b(and|or|not)\b/gi, (match, group1: string | undefined) =>
      group1 ? group1.toUpperCase() : match,
    )
    // Clamp invalid dates in received>= / received<= / sent>= / sent<= filters
    .replace(
      /\b((?:received|sent)[<>]=?)(\d{4}-\d{2}-\d{2})\b/gi,
      (_, op: string, date: string) => `${op}${clampToValidDate(date) as string}`,
    )
    // Strip unsupported prop:"quoted value" clauses
    .replace(/\b(\w+):"[^"]*"\s*/gi, (match, prop: string) =>
      SUPPORTED_KQL_PROPERTIES.has(prop.toLowerCase()) ? match : '',
    )
    // Strip unsupported prop:unquotedValue clauses (negative lookahead avoids
    // double-matching quoted values already handled above)
    .replace(/\b(\w+):(?!")\S+\s*/gi, (match, prop: string) =>
      SUPPORTED_KQL_PROPERTIES.has(prop.toLowerCase()) ? match : '',
    )
    .trim();

  return quoteKqlClauses(sanitized);
}
