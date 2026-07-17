export interface ParsedEmail {
  from: string;
  to: string[];
  cc: string[];
  subject: string;
  date: string;
  body: string;
}

const splitAddresses = (value: string | undefined): string[] =>
  value
    ? value
        .split(',')
        .map((address) => address.trim())
        .filter(Boolean)
    : [];

export function parseRawEmail(rawEmail: string): ParsedEmail {
  const normalized = rawEmail.replaceAll('\r\n', '\n').trim();
  const separatorIndex = normalized.indexOf('\n\n');
  if (separatorIndex === -1) {
    throw new Error('Paste a raw email containing headers followed by the message body.');
  }

  const headerBlock = normalized.slice(0, separatorIndex);
  const body = normalized.slice(separatorIndex + 2).trim();
  const unfoldedHeaders = headerBlock.replace(/\n[ \t]+/g, ' ');
  const headers = new Map<string, string>();

  for (const line of unfoldedHeaders.split('\n')) {
    const delimiterIndex = line.indexOf(':');
    if (delimiterIndex <= 0) {
      continue;
    }

    const name = line.slice(0, delimiterIndex).trim().toLowerCase();
    const value = line.slice(delimiterIndex + 1).trim();
    headers.set(name, value);
  }

  const from = headers.get('from') ?? '';
  const subject = headers.get('subject') ?? '';
  if (!from || !subject || !body) {
    throw new Error('The pasted email must include From, Subject, and a message body.');
  }

  const rawDate = headers.get('date') ?? '';
  const parsedTimestamp = Date.parse(rawDate);

  return {
    from,
    to: splitAddresses(headers.get('to')),
    cc: splitAddresses(headers.get('cc')),
    subject,
    date: Number.isNaN(parsedTimestamp) ? rawDate : new Date(parsedTimestamp).toISOString(),
    body,
  };
}
