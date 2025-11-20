import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { getItemUrl } from '../utils/sharepoint.util';

export interface SharepointMetadata extends Record<string, unknown> {
  readonly link: string;
  readonly path: string;
  readonly filename: string;
  readonly siteId: string;
  readonly siteWebUrl: string;
  readonly driveId: string;
  readonly driveName: string;
  readonly itemId: string;
  readonly itemType: SharepointContentItem['itemType'];
  readonly createdAt?: string;
  readonly modifiedAt?: string;
  readonly author?: string;
  readonly page?: string;
  readonly newsTaf?: unknown;
  readonly fields?: Record<string, unknown>;
}

export function buildSharepointMetadata(
  sharepointContentItem: SharepointContentItem,
): SharepointMetadata {
  const fields = extractFields(sharepointContentItem);

  return {
    link: getItemUrl(sharepointContentItem),
    path: sharepointContentItem.folderPath,
    filename: sharepointContentItem.fileName,
    siteId: sharepointContentItem.siteId,
    siteWebUrl: sharepointContentItem.siteWebUrl,
    driveId: sharepointContentItem.driveId,
    driveName: sharepointContentItem.driveName,
    itemId: sharepointContentItem.item.id,
    itemType: sharepointContentItem.itemType,
    createdAt: resolveCreatedAt(sharepointContentItem, fields),
    modifiedAt: resolveModifiedAt(sharepointContentItem, fields),
    author: resolveAuthor(sharepointContentItem, fields),
    page: resolvePage(fields),
    newsTaf: getFieldCaseInsensitive(fields, 'NewsTaf'),
    fields,
  };
}

function extractFields(
  sharepointContentItem: SharepointContentItem,
): Record<string, unknown> | undefined {
  if (sharepointContentItem.itemType === 'driveItem') {
    return sharepointContentItem.item.listItem?.fields;
  }
  return sharepointContentItem.item.fields;
}

function resolveCreatedAt(
  sharepointContentItem: SharepointContentItem,
  fields?: Record<string, unknown>,
): string | undefined {
  const createdFromFields = getFieldAsString(fields, 'Created');
  if (createdFromFields) return createdFromFields;

  return sharepointContentItem.itemType === 'driveItem'
    ? sharepointContentItem.item.listItem?.createdDateTime
    : sharepointContentItem.item.createdDateTime;
}

function resolveModifiedAt(
  sharepointContentItem: SharepointContentItem,
  fields?: Record<string, unknown>,
): string | undefined {
  const modifiedFromFields = getFieldAsString(fields, 'Modified');
  if (modifiedFromFields) return modifiedFromFields;

  return sharepointContentItem.itemType === 'driveItem'
    ? sharepointContentItem.item.listItem?.lastModifiedDateTime
    : sharepointContentItem.item.lastModifiedDateTime;
}

function resolveAuthor(
  sharepointContentItem: SharepointContentItem,
  fields?: Record<string, unknown>,
): string | undefined {
  const createdBy =
    sharepointContentItem.itemType === 'driveItem'
      ? sharepointContentItem.item.listItem?.createdBy?.user
      : sharepointContentItem.item.createdBy?.user;

  if (createdBy?.displayName?.trim()) return createdBy.displayName;
  if (createdBy?.email?.trim()) return createdBy.email;

  return (
    getFieldAsString(fields, 'Author') ??
    getFieldAsString(fields, 'Editor') ??
    getFieldAsString(fields, 'AuthorLookupId') ??
    getFieldAsString(fields, 'EditorLookupId')
  );
}

function resolvePage(fields?: Record<string, unknown>): string | undefined {
  return (
    getFieldAsString(fields, 'Page') ??
    getFieldAsString(fields, 'Title') ??
    getFieldAsString(fields, 'FileLeafRef')
  );
}

function getFieldAsString(
  fields: Record<string, unknown> | undefined,
  key: string,
): string | undefined {
  if (!fields) return undefined;

  const value = fields[key];
  if (typeof value !== 'string') return undefined;

  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

function getFieldCaseInsensitive(
  fields: Record<string, unknown> | undefined,
  key: string,
): unknown {
  if (!fields) return undefined;
  const match = Object.keys(fields).find(
    (existingKey) => existingKey.toLowerCase() === key.toLowerCase(),
  );
  if (!match) return undefined;
  return fields[match];
}
