import { ConfigService } from '@nestjs/config';
import type { Config } from '../config';
import { normalizeSlashes } from './paths.util';

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

export function smearPath(path: string | null | undefined, leaveOver = 4): string {
  if (path === undefined || path === null) {
    return '__erroneous__';
  }
  const normalizedPath = normalizeSlashes(path);
  const smearedNormalizedPath = normalizedPath
    .split('/')
    .map((segment) => smear(segment, leaveOver))
    .join('/');

  return `/${smearedNormalizedPath}`;
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

/**
 * Recursively redacts all values in an object structure while preserving the keys and structure.
 * This is useful for logging sensitive data where you want to show the structure but hide all values.
 * Preserves null and undefined values as they are not considered sensitive data.
 */
export function redactAllValues(obj: unknown): unknown {
  if (obj === null || obj === undefined) {
    return obj;
  }

  if (typeof obj !== 'object') {
    return '***';
  }

  if (Array.isArray(obj)) {
    return obj.map(redactAllValues);
  }

  // For non-plain objects (Date, RegExp, functions) redact the whole thing
  const proto = Object.getPrototypeOf(obj);
  if (proto !== Object.prototype && proto !== null) {
    return '***';
  }

  const result: Record<string | symbol, unknown> = {};

  // Handle all property keys including symbols
  const keys = [...Object.getOwnPropertyNames(obj), ...Object.getOwnPropertySymbols(obj)];

  for (const key of keys) {
    result[key] = redactAllValues((obj as Record<string | symbol, unknown>)[key]);
  }

  return result;
}

export function shouldConcealLogs(configService: ConfigService<Config, true>): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
