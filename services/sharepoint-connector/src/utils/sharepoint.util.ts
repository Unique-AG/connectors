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
 * Gets the web URL for a SharePoint item with ?web=1 parameter.
 *
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/sites/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/sites/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 */
export function getItemUrl(sharepointContentItem: SharepointContentItem): string {
  let url: string;

  if (sharepointContentItem.itemType === 'driveItem') {
    url = sharepointContentItem.item.listItem?.webUrl || sharepointContentItem.item.webUrl;
  } else if (sharepointContentItem.itemType === 'listItem') {
    url = sharepointContentItem.item.webUrl;
  } else {
    assert.fail('Invalid pipeline item type');
  }

  return url.includes('?') ? `${url}&web=1` : `${url}?web=1`;
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
 */
export function buildIngestionItemKey(sharepointContentItem: SharepointContentItem): string {
  return `${sharepointContentItem.siteId}/${sharepointContentItem.item.id}`;
}

export function extractFolderPathFromUrl(fileUrl: string): string {
  try {
    const urlObj = new URL(fileUrl);
    const pathName = decodeURIComponent(urlObj.pathname);

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

    // Remove leading slash
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
    throw new Error(
      `Failed to extract folder path from URL "${fileUrl}": ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export function buildScopePathFromItem(item: SharepointContentItem, rootScopeName: string): string {
  const fileUrl = extractFileUrl(item);
  const folderPath = extractFolderPathFromUrl(fileUrl);
  return `${rootScopeName}/${folderPath}`;
}

function extractFileUrl(item: SharepointContentItem): string {
  if (item.itemType === 'driveItem') {
    return item.item.listItem?.webUrl || item.item.webUrl;
  }
  return item.item.webUrl;
}
