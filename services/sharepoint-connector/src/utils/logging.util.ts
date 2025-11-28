export function smear(text: string | null | undefined, leaveOver = 4) {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  if (!text.length || text.length <= leaveOver) return '[Smeared]';
  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(/[a-zA-Z0-9_]/g, '*')}${end}`;
}

export function redact(text: string | null | undefined, ends = 2): string {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  const end = text.length;
  const middleLength = end - 2 * ends;
  if (middleLength < 3) return '[Redacted]';
  return `${text.substring(0, ends)}[Redacted]${text.substring(end - ends, end)}`;
}

const SHAREPOINT_SITE_NAME_REGEX = /\/sites\/((?![a-f0-9-]{36}(?:\/|$))[^/]+)\//gi;

export function redactSiteNameFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_NAME_REGEX, (_, siteName) => `/sites/${redact(siteName)}/`);
}

const SHAREPOINT_SITE_ID_REGEX = /\/sites\/([a-f0-9-]{36})(?=\/|$)/gi;

export function smearSiteIdFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_ID_REGEX, (_, siteId) => `/sites/${smear(siteId)}`);
}

export function concealIngestionKey(key: string): string {
  const parts = key.split('/');
  if (parts.length >= 2 && parts[0] && parts[0].length > 0) {
    // First part is siteId, rest is item path
    const [siteId, ...rest] = parts;
    return `${smear(siteId)}/${rest.join('/')}`;
  }
  return smear(key); // Smear the whole key if format is unexpected
}

export function shouldConcealLogs(configService: {
  get: (key: string, options: { infer: true }) => 'conceal' | 'disclose';
}): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
