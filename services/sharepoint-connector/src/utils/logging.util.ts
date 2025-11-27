/**
 * Blurrs the text but keeps its length
 * @param text Text to be smeared
 * @param leaveOver How many characters should be left, recommended and default: 4
 * @returns Smeared string
 */
export function smear(text: string, leaveOver = 4) {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  if (!text.length) return '[Smeared]';
  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(/[a-zA-Z0-9_]/g, '*')}${end}`;
}

/**
 * Completely redacts the text and blurrs the length
 * @param text Text to be redacted
 * @param ends How many characters should be left at both ends, recommended and default: 2
 * @returns Redacted string
 */
export function redact(text: string, ends = 2): string {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  const end = text.length;
  if (2 * ends > text.length) return '[Redacted]';
  return `${text.substring(0, ends)}[Redacted]${text.substring(end - ends, end)}`;
}

/**
 * Regex pattern to match and capture SharePoint site names in REST API paths.
 * Matches: /sites/{siteName}/
 */
const SHAREPOINT_SITE_NAME_REGEX = /\/sites\/([^/]+)\//g;

/**
 * Redacts SharePoint site names from API paths for secure logging.
 * @param path The API path containing site names to redact
 * @returns The path with site names redacted using the redact function
 */
export function redactSiteNameFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_NAME_REGEX, (_, siteName) => `/sites/${redact(siteName)}/`);
}

/**
 * Checks if logs should be concealed based on the LOGS_DIAGNOSTICS_DATA_POLICY configuration
 * @param configService The config service instance
 * @returns true if logs should be concealed, false if they should be disclosed
 */
export function concealLogs(configService: {
  get: (key: string, options: { infer: true }) => 'conceal' | 'disclose';
}): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
