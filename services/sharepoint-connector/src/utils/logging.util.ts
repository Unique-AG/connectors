import { ConfigService } from '@nestjs/config';
import { regexes } from 'zod';
import type { Config } from '../config';
export const EXTERNAL_ID_PREFIX = 'spc:' as const;
export const PENDING_DELETE_PREFIX = 'spc:pending-delete:' as const;

// SharePoint reserved virtual directories that appear after the site/subsite path. Used as
// terminators to distinguish multi-segment subsite names from library/folder segments.
// https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/determine-sharepoint-rest-service-endpoint-uris (_api)
// https://learn.microsoft.com/en-us/sharepoint/dev/general-development/urls-and-tokens-in-sharepoint (_layouts)
// https://learn.microsoft.com/en-us/sharepoint/dev/general-development/basic-uri-structure-and-path (_vti_bin)
const SHAREPOINT_SITE_NAME_REGEX =
  /\/(sites|teams)\/((?![a-f0-9-]{36}(?:\/|$))[^/]+(?:\/[^/]+)*?)\/(_api|_layouts|_vti_bin)\//gi;

const guidPattern = regexes.guid.source.slice(2, -2);
const SHAREPOINT_SITE_ID_REGEX = new RegExp(
  `/(sites|teams)/(${guidPattern}|[^/,]+,${guidPattern},${guidPattern})(?=/|$)`,
  'gi',
);

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
  return path.replace(
    SHAREPOINT_SITE_NAME_REGEX,
    (_, managedPath: string, siteName: string, keyword: string) =>
      `/${managedPath}/${siteName
        .split('/')
        .map((segment) => smear(segment))
        .join('/')}/${keyword}/`,
  );
}

export function smearSiteIdFromPath(path: string): string {
  return path.replace(SHAREPOINT_SITE_ID_REGEX, (_, managedPath: string, siteId: string) => {
    const smeared = siteId.includes(',')
      ? siteId
          .split(',')
          .map((part) => smear(part))
          .join(',')
      : smear(siteId);
    return `/${managedPath}/${smeared}`;
  });
}

export function shouldConcealLogs(configService: ConfigService<Config, true>): boolean {
  return configService.get('app.logsDiagnosticsDataPolicy', { infer: true }) === 'conceal';
}
