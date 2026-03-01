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
 * Builds the key portion submitted to the file-diff API.
 *
 * The diff API scopes to items whose full key starts with `partialKey/` (the parent siteId) and
 * compares the remainder against submitted keys. For main-site items the remainder is just the
 * itemId; for subsite items it is `subsiteId/itemId`.
 */
export function buildFileDiffKey(sharepointContentItem: SharepointContentItem): string {
  if (sharepointContentItem.syncSiteId) {
    return `${sharepointContentItem.siteId.value}/${sharepointContentItem.item.id}`;
  }
  return sharepointContentItem.item.id;
}

/**
 * Builds a unique hierarchical key for ingestion.
 *
 * Main-site items:  `{siteId}/{itemId}`
 * Subsite items:    `{parentSiteId}/{subsiteId}/{itemId}`
 */
export function buildIngestionItemKey(sharepointContentItem: AnySharepointItem): string {
  if (sharepointContentItem.syncSiteId) {
    return `${sharepointContentItem.syncSiteId.value}/${sharepointContentItem.siteId.value}/${sharepointContentItem.item.id}`;
  }
  return `${sharepointContentItem.siteId.value}/${sharepointContentItem.item.id}`;
}

/**
 * Extracts a relative path from a SharePoint URL, stripping the /sites/{siteName} prefix.
 *
 * For regular sites (siteName = "SiteName"), strips /sites/SiteName.
 * For subsites (siteName = "SiteName/SubSite"), strips /sites/SiteName/SubSite.
 *
 * We need to pass siteName because in the url, subsite is indistinguishable from a library. If you
 * have a subsite named SubsiteA and a library called DriveB, the urls will simply be
 * https://tenant.sharepoint.com/sites/SiteName/SubsiteA and
 * https://tenant.sharepoint.com/sites/SiteName/DriveB with no indication which is which. To
 * distinguish between the two, we need to pass the siteName to the function.
 */
function getRelativeUniquePathFromUrl(url: string, siteName: Smeared): string {
  const urlObj = new URL(url);
  const pathName = decodeURIComponent(urlObj.pathname);

  const siteNameSegmentCount = normalizeSlashes(siteName.value).split('/').length;
  const relativePath = normalizeSlashes(pathName)
    .split('/')
    .slice(1 + siteNameSegmentCount)
    .join('/');
  return relativePath ? `/${relativePath}` : '/';
}

function getRelativeUniqueParentPathFromUrl(url: string, siteName: Smeared): string {
  const uniqueItemPath = getRelativeUniquePathFromUrl(url, siteName);
  const lastSlashIndex = uniqueItemPath.lastIndexOf('/');

  if (lastSlashIndex > 0) {
    return uniqueItemPath.substring(0, lastSlashIndex);
  }
  return '';
}

export function getUniquePathFromItem(
  item: AnySharepointItem,
  rootPath: Smeared,
  siteName: Smeared,
): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniquePath = getRelativeUniquePathFromUrl(fileUrl, siteName);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniquePath}`);
}

export function getUniqueParentPathFromItem(
  item: AnySharepointItem,
  rootPath: Smeared,
  siteName: Smeared,
): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  const fileUrl = extractFileUrl(item);
  const uniqueParentPath = getRelativeUniqueParentPathFromUrl(fileUrl, siteName);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniqueParentPath}`);
}

function extractFileUrl(item: AnySharepointItem): string {
  if (item.itemType === 'driveItem') {
    return item.item.listItem?.webUrl || item.item.webUrl;
  }
  return item.item.webUrl;
}
