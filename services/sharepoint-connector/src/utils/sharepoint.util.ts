import assert from 'node:assert';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';

interface SharepointFileKeyParams {
  scopeId?: string | null;
  siteId: string;
  driveName: string;
  folderPath: string;
  fileId: string;
  fileName: string;
}

interface SharepointPartialKeyParams {
  scopeId?: string | null;
  siteId: string;
}

export const normalizeSlashes = (value: string): string => {
  // 1. Remove leading/trailing whitespace
  let result = value.trim();

  // 2. Remove leading and trailing slashes
  result = result.replace(/^\/+|\/+$/g, '');

  // 3. Replace multiple consecutive slashes with single slash
  result = result.replace(/\/+/g, '/');

  return result;
};

export function buildSharepointFileKey({
  scopeId,
  siteId,
  driveName,
  folderPath,
  fileId,
  fileName,
}: SharepointFileKeyParams): string {
  if (scopeId) {
    return `sharepoint_scope_${scopeId}_${fileId}`;
  }

  const normalizedSiteId = normalizeSlashes(siteId);
  const normalizedDriveName = normalizeSlashes(driveName);
  const normalizedFolderPath = normalizeSlashes(folderPath);

  const segments = [normalizedSiteId, normalizedDriveName, normalizedFolderPath, fileName]
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);

  return segments.join('/');
}

export function buildSharepointPartialKey({ scopeId, siteId }: SharepointPartialKeyParams): string {
  if (scopeId) {
    return `sharepoint_scope_${scopeId}_`;
  }

  return normalizeSlashes(siteId);
}

/**
 * Gets the web URL for a SharePoint item, with optional scope prefix.
 *
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/sites/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/sites/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 *
 * When rootScopeName is provided, the protocol is stripped from the URL to prevent
 * creating scopes like "my-scope/https://uniqueapp.sharepoint.com" instead of "my-scope"
 */
export function getItemUrl(
  sharepointContentItem: SharepointContentItem,
  rootScopeName?: string,
): string {
  const url = getBaseUrl(sharepointContentItem);

  return rootScopeName
    ? `${rootScopeName}/${stripProtocol(url)}`
    : url;
}

function getBaseUrl(item: SharepointContentItem): string {
  if (item.itemType === 'driveItem') {
    const listItemUrl = item.item.listItem?.webUrl;
    return listItemUrl
      ? `${listItemUrl}?web=1`
      : item.item.webUrl;
  }

  if (item.itemType === 'listItem') {
    return `${item.item.webUrl}?web=1`;
  }

  assert.fail('Invalid pipeline item type');
}

export function buildFileDiffKey(sharepointContentItem: SharepointContentItem): string {
  return sharepointContentItem.item.id;
}

export function buildIngetionItemKey(sharepointContentItem: SharepointContentItem): string {
  if (sharepointContentItem.itemType === 'listItem') {
    return `${sharepointContentItem.siteId}/${sharepointContentItem.driveId}/${sharepointContentItem.item.id}`; // TODO check if they always are reingested
  }

  return `${sharepointContentItem.siteId}/${sharepointContentItem.item.id}`;
}

function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, '');
}
