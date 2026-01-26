import { ConfigService } from '@nestjs/config';
import type { Config } from '../config';
import { normalizeSlashes } from './paths.util';

export const EXTERNAL_ID_PREFIX = 'spc:' as const;

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

export function smearPath(
  path: string | null | undefined,
  leaveOver = 4,
  options: { addLeadingSlash?: boolean } = { addLeadingSlash: true },
): string {
  if (path === undefined || path === null) {
    return '__erroneous__';
  }
  const normalizedPath = normalizeSlashes(path);
  const smearedNormalizedPath = normalizedPath
    .split('/')
    .map((segment) => smear(segment, leaveOver))
    .join('/');

  return options.addLeadingSlash ? `/${smearedNormalizedPath}` : smearedNormalizedPath;
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

export function smearExternalId(externalId: string | null | undefined): string {
  if (externalId === undefined || externalId === null) {
    // prints __erroneous__ instead of the original value
    return smear(externalId);
  }

  if (externalId.startsWith(EXTERNAL_ID_PREFIX)) {
    const idPart = externalId.substring(EXTERNAL_ID_PREFIX.length);

    // Check if it's a type-prefixed ID like "site:..." or "folder:..."
    const firstColonIndex = idPart.indexOf(':');
    if (firstColonIndex !== -1) {
      const type = idPart.substring(0, firstColonIndex + 1);
      const actualId = idPart.substring(firstColonIndex + 1);

      if (actualId.includes('/')) {
        return `${EXTERNAL_ID_PREFIX}${type}${smearPath(actualId, 4, { addLeadingSlash: false })}`;
      }
      return `${EXTERNAL_ID_PREFIX}${type}${smear(actualId)}`;
    }

    // Special case like spc:siteId/sitePages
    if (idPart.includes('/')) {
      return `${EXTERNAL_ID_PREFIX}${smearPath(idPart, 4, { addLeadingSlash: false })}`;
    }

    // Fallback for spc:something (no second colon, no slash)
    return `${EXTERNAL_ID_PREFIX}${smear(idPart)}`;
  }

  return smear(externalId);
}

export function shouldConcealLogs(configService: ConfigService<Config, true>): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
