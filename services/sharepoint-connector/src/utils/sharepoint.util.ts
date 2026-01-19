import assert from 'node:assert';
import type {
  AnySharepointItem,
  SharepointContentItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { normalizeSlashes } from './paths.util';

/**
 * Gets the web URL for a SharePoint item with ?web=1 parameter.
 *
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/sites/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/sites/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 */
export function getItemUrl(sharepointContentItem: SharepointContentItem): string {
  const url = extractFileUrl(sharepointContentItem);
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
export function buildIngestionItemKey(sharepointContentItem: AnySharepointItem): string {
  return `${sharepointContentItem.siteId}/${sharepointContentItem.item.id}`;
}

// Gets SharePoint URL and returns the relative unique path like without context of the root scope
// Example 1:
// https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf/Extensa%205635_5635g_5635z_5635zg_5235%20(ba50_mv).pdf
// returns
// /TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf/Extensa%205635_5635g_5635z_5635zg_5235%20(ba50_mv).pdf
// Example 2:
// https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files
// returns
// /TestTeamSite/Shared%20Documents/lorand%27s%20files
function getRelativeUniquePathFromUrl(url: string, siteName?: string): string {
  const urlObj = new URL(url);
  const pathName = decodeURIComponent(urlObj.pathname);

  // Path start with /sites/ and we don't want to include it in the path
  let relativePath = normalizeSlashes(pathName.replace(/\/sites\//, '/'));

  if (siteName) {
    const segments = relativePath.split('/');
    // We remove the first segment (expected to be site name) to avoid redundant nesting
    // because we already ingest into a site-specific root scope.
    segments.shift();
    relativePath = segments.join('/');
  }

  return `/${normalizeSlashes(relativePath)}`;
}

// Gets SharePoint URL and returns the relative unique parent path like without context of the root scope
// Example 1:
// https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf/Extensa%205635_5635g_5635z_5635zg_5235%20(ba50_mv).pdf
// returns
// /TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf
// Example 2:
// https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files
// returns
// /TestTeamSite/Shared%20Documents
function getRelativeUniqueParentPathFromUrl(url: string, siteName?: string): string {
  const uniqueItemPath = getRelativeUniquePathFromUrl(url, siteName);
  const lastSlashIndex = uniqueItemPath.lastIndexOf('/');
  if (lastSlashIndex !== -1) {
    return uniqueItemPath.substring(0, lastSlashIndex);
  }
  // This case shouldn't really happen because the path will always at least have {site}/{drive}
  return '';
}

export function getUniquePathFromItem(
  item: AnySharepointItem,
  rootPath: string,
  siteName?: string,
): string {
  assert.ok(rootPath, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniquePath = getRelativeUniquePathFromUrl(fileUrl, siteName);

  return `/${normalizeSlashes(rootPath)}${uniquePath}`;
}

export function getUniqueParentPathFromItem(
  item: AnySharepointItem,
  rootPath: string,
  siteName?: string,
): string {
  assert.ok(rootPath, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniqueParentPath = getRelativeUniqueParentPathFromUrl(fileUrl, siteName);

  return `/${normalizeSlashes(rootPath)}${uniqueParentPath}`;
}

function extractFileUrl(item: AnySharepointItem): string {
  if (item.itemType === 'driveItem') {
    return item.item.listItem?.webUrl || item.item.webUrl;
  }
  return item.item.webUrl;
}
