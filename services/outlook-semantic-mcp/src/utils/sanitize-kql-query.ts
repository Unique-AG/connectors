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

export function sanitizeKqlQuery(kql: string): string {
  return (
    kql
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
      .trim()
  );
}
