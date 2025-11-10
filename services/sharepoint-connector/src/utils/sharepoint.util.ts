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
 * Gets the web URL for a SharePoint item, with optional root scope name prefix and stripped path prefixes.
 *
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/sites/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/sites/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 *
 * When rootScopeName is provided, unnecessary path prefixes are always stripped from the URL.
 * Instead of "my-scope/uniqueapp.sharepoint.com/sites/site-name/path/file.pdf",
 * the result is "my-scope/site-name/path/file.pdf".
 */
export function getItemUrl(
  sharepointContentItem: SharepointContentItem,
  rootScopeName?: string,
): string {
  const url = getBaseUrl(sharepointContentItem);

  if (!rootScopeName) {
    return url;
  }

  const simplifiedPath = stripSharepointPathPrefixes(url);
  return `${rootScopeName}/${simplifiedPath}`;
}

function getBaseUrl(item: SharepointContentItem): string {
  if (item.itemType === 'driveItem') {
    const listItemUrl = item.item.listItem?.webUrl;
    const url = listItemUrl || item.item.webUrl;
    return appendWebParameter(url);
  }

  if (item.itemType === 'listItem') {
    return appendWebParameter(item.item.webUrl);
  }

  assert.fail('Invalid pipeline item type');
}

function appendWebParameter(url: string): string {
  if (url.includes('?')) {
    return `${url}&web=1`;
  }
  return `${url}?web=1`;
}

/**
 * Strips the SharePoint domain and 'sites' prefix from a URL.
 *
 * Examples:
 * - "https://company.sharepoint.com/sites/mysite/Shared Documents/folder/file.pdf"
 *   becomes "mysite/Shared Documents/folder/file.pdf"
 * - "https://company.sharepoint.com/sites/mysite/folder/file.pdf?web=1"
 *   becomes "mysite/folder/file.pdf?web=1"
 */
function stripSharepointPathPrefixes(url: string): string {
  // Remove protocol
  let path = url.replace(/^https?:\/\//, '');

  // Remove domain (e.g., "uniqueapp.sharepoint.com/")
  path = path.replace(/^[^/]+\//, '');

  // Remove "sites/" prefix if present
  path = path.replace(/^sites\//, '');

  return path;
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
    throw new Error(
      `Failed to extract folder path from URL "${fileUrl}": ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export function buildScopePathFromItem(
  item: SharepointContentItem,
  rootScopeName: string,
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
  return `${rootScopeName}/${folderPath}`;
}
