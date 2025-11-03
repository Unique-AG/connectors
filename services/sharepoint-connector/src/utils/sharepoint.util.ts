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

  return rootScopeName ? `${rootScopeName}/${stripProtocol(url)}` : url;
}

function getBaseUrl(item: SharepointContentItem): string {
  if (item.itemType === 'driveItem') {
    const listItemUrl = item.item.listItem?.webUrl;
    return listItemUrl ? `${listItemUrl}?web=1` : item.item.webUrl;
  }

  if (item.itemType === 'listItem') {
    return `${item.item.webUrl}?web=1`;
  }

  assert.fail('Invalid pipeline item type');
}

/**
 * Builds a key for file-diff comparison.
 *
 * File-diff only compares the last segment of a path (e.g., in "key1/key2/key3", only "key3" is compared).
 * Therefore, we use only the item ID as the key. For a full hierarchical key, see buildIngestionItemKey.
 */
export function buildFileDiffKey(sharepointContentItem: SharepointContentItem): string {
  return sharepointContentItem.item.id;
}

/**
 * Builds a unique hierarchical key for ingestion.
 *
 * Ingestion requires a complete hierarchical key (e.g., "siteId/itemId") to ensure uniqueness of the stored key
 * across different scopes and drives. This differs from buildFileDiffKey which only uses the item ID.
 */
export function buildIngestionItemKey(sharepointContentItem: SharepointContentItem): string {
  if (sharepointContentItem.itemType === 'listItem') {
    return `${sharepointContentItem.siteId}/${sharepointContentItem.driveId}/${sharepointContentItem.item.id}`;
  }

  return `${sharepointContentItem.siteId}/${sharepointContentItem.item.id}`;
}

function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, '');
}

export function extractFolderPathFromUrl(fileUrl: string): string {
  try {
    const urlObj = new URL(fileUrl);
    const pathName = urlObj.pathname;

    // Extract site name: /sites/siteName or /sites/siteName/
    const siteMatch = pathName.match(/\/sites\/([^/]+)/);
    assert(siteMatch, 'Unable to extract site name from URL');
    const siteName = siteMatch[1];
    assert(siteName, 'Site name is empty');

    // Extract path after site name
    const afterSite = pathName.substring(siteMatch[0].length);
    if (!afterSite || afterSite === '/') {
      return siteName;
    }

    // Remove leading slash and trailing filename
    let path = afterSite.replace(/^\//, '');
    if (!path) {
      return siteName;
    }
    
    // Remove filename (last segment after last slash)
    const lastSlashIndex = path.lastIndexOf('/');
    if (lastSlashIndex > 0) {
      const folderPath = path.substring(0, lastSlashIndex);
      assert(folderPath, 'Folder path is empty');
      path = folderPath;
    } else {
      // No folder, file is in root
      return siteName;
    }

    // Normalize slashes and combine
    const normalizedPath = normalizeSlashes(path);
    assert(normalizedPath, 'Normalized path is empty');
    return `${siteName}/${normalizedPath}`;
  } catch (error) {
    throw new Error(`Failed to extract folder path from URL "${fileUrl}": ${error instanceof Error ? error.message : String(error)}`);
  }
}

export function buildScopePathFromItem(
  item: SharepointContentItem,
  ingestionScopeLocation: string,
): string {
  const getFileUrl = (contentItem: SharepointContentItem): string => {
    if (contentItem.itemType === 'driveItem') {
      return contentItem.item.listItem?.webUrl || contentItem.item.webUrl || '';
    }
    return contentItem.item.webUrl || '';
  };

  const fileUrl = getFileUrl(item);
  assert(fileUrl, 'Unable to determine file URL from item');

  const folderPath = extractFolderPathFromUrl(fileUrl);
  return `${ingestionScopeLocation}/${folderPath}`;
}
