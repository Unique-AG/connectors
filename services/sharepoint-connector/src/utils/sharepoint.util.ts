import assert from 'node:assert';
import type {
  AnySharepointItem,
  SharepointContentItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { normalizeSlashes } from './paths.util';
import { createSmeared, type Smeared } from './smeared';

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
  return `${sharepointContentItem.siteId.value}/${sharepointContentItem.item.id}`;
}

/**
 * Extracts a relative path from a SharePoint URL.
 *
 * We always strip the site segment (the first segment after /sites/) from the path
 * to avoid redundant nesting, as we already ingest into site-specific root scopes.
 */
function getRelativeUniquePathFromUrl(url: string): string {
  const urlObj = new URL(url);
  const pathName = decodeURIComponent(urlObj.pathname);

  // SharePoint paths look like /sites/SiteName/Library/Folder/File
  // We remove the first two segments ('sites' and 'SiteName') to avoid redundant nesting, as we already ingest into site-specific root scopes.
  const relativePath = normalizeSlashes(pathName).split('/').slice(2).join('/');
  return relativePath ? `/${relativePath}` : '/';
}

/**
 * Extracts the relative parent path from a SharePoint URL.
 */
function getRelativeUniqueParentPathFromUrl(url: string): string {
  const uniqueItemPath = getRelativeUniquePathFromUrl(url);
  const lastSlashIndex = uniqueItemPath.lastIndexOf('/');

  // If the path is just "/" or "/Segment", the parent is the root "" (relative to rootPath)
  if (lastSlashIndex > 0) {
    return uniqueItemPath.substring(0, lastSlashIndex);
  }
  // This case shouldn't really happen because the path will always at least have {site}/{drive}
  return '';
}

export function getUniquePathFromItem(item: AnySharepointItem, rootPath: Smeared): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniquePath = getRelativeUniquePathFromUrl(fileUrl);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniquePath}`);
}

export function getUniqueParentPathFromItem(item: AnySharepointItem, rootPath: Smeared): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniqueParentPath = getRelativeUniqueParentPathFromUrl(fileUrl);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniqueParentPath}`);
}

function extractFileUrl(item: AnySharepointItem): string {
  if (item.itemType === 'driveItem') {
    return item.item.listItem?.webUrl || item.item.webUrl;
  }
  return item.item.webUrl;
}
