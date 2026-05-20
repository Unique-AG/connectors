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

/**
 * Wraps the entire KQL expression in outer double quotes, escaping any inner
 * double quotes. AND is dropped because the Graph API treats spaces as implicit
 * AND; OR and NOT are kept as explicit keywords.
 *
 *   subject:"Request for access" from:alex@domain.com
 *     → "subject:\"Request for access\" from:alex@domain.com"
 *
 *   from:alex@domain.com OR subject:hello
 *     → "from:alex@domain.com OR subject:hello"
 */
function quoteKqlClauses(kql: string): string {
  if (!kql) {
    return kql;
  }

  // Normalize single-quoted property values to double-quoted: prop:'value' → prop:"value"
  const normalized = kql.replace(/\b(\w+):'([^']*)'/g, '$1:"$2"');

  // Drop explicit AND — the Graph API treats spaces as implicit AND.
  // The alternation skips double-quoted phrases so that subject:"budget AND plan"
  // is not mangled; bare AND between clauses (bounded by whitespace/string edges)
  // is replaced with a space. Property values like subject:and-report are not
  // touched because AND there is not surrounded by whitespace.
  const withoutAnd = normalized
    .replace(/"[^"]*"|(?:^|\s)AND(?:\s|$)/g, (match) => (match.startsWith('"') ? match : ' '))
    .replace(/\s+/g, ' ')
    .trim();

  return `"${withoutAnd.replace(/(?<!\\)"/g, '\\"')}"`;
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
