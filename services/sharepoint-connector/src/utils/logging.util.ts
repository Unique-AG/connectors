import { ConfigService } from '@nestjs/config';
import type { Config } from '../config';
export const EXTERNAL_ID_PREFIX = 'spc:' as const;

const SHAREPOINT_SITE_NAME_REGEX = /\/sites\/((?![a-f0-9-]{36}(?:\/|$))[^/]+)\//gi;
const SHAREPOINT_SITE_ID_REGEX = /\/sites\/([a-f0-9-]{36})(?=\/|$)/gi;

export function smear(text: string | null | undefined, leaveOver = 4) {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  if (!text.length || text.length <= leaveOver) return '[Smeared]';

  const charsToSmear = text.length - leaveOver;
  if (charsToSmear < 3) return '[Smeared]';

  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(/[a-zA-Z0-9_]/g, '*')}${end}`;
}

export function smearSiteNameFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_NAME_REGEX, (_, siteName) => `/sites/${smear(siteName)}/`);
}

export function smearSiteIdFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_ID_REGEX, (_, siteId) => `/sites/${smear(siteId)}`);
}

export function shouldConcealLogs(configService: ConfigService<Config, true>): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
