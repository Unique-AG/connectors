import assert from 'node:assert';
import type {
  AnySharepointItem,
  SharepointContentItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { normalizeSlashes } from './paths.util';
import { createSmeared, type Smeared } from './smeared';

type ListItemAttachment = Extract<SharepointContentItem, { itemType: 'listItemAttachment' }>;

// SharePoint REST returns `ServerRelativeUrl` decoded, so names with spaces, `%` or `#` must be
// encoded per segment to form a working link.
export function buildAttachmentAbsoluteUrl(baseUrl: string, serverRelativeUrl: string): string {
  const origin = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  const encodedPath = normalizeSlashes(serverRelativeUrl)
    .split('/')
    .map(encodeURIComponent)
    .join('/');
  return `${origin}/${encodedPath}`;
}

/**
 * Gets the web URL for a SharePoint item with ?web=1 parameter.
 *
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/{sites|teams}/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/{sites|teams}/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 */
export function getItemUrl(sharepointContentItem: SharepointContentItem): string {
  const url = extractFileUrl(sharepointContentItem);
  return url.includes('?') ? `${url}&web=1` : `${url}?web=1`;
}

/**
 * Separator between the segments of a file key below the site: subsite ID, list ID, item ID and
 * attachment file name. We use `::` instead of `/` because the file-diff API splits stored keys by
 * `/` and compares only the last segment. Using `/` would lose the leading segments and produce
 * phantom new+deleted results.
 */
export const KEY_SEPARATOR = '::';

/**
 * Builds the key portion submitted to the file-diff API.
 *
 * The diff API scopes to items whose full key starts with `partialKey/` (the parent siteId) and
 * compares the remainder against submitted keys:
 *
 * Main-site items:        `{itemId}`
 * Subsite items:          `{subsiteId}::{itemId}`
 * Main-site attachments:  `{listId}::{itemId}::{fileName}`
 * Subsite attachments:    `{subsiteId}::{listId}::{itemId}::{fileName}`
 */
export function buildFileDiffKey(sharepointContentItem: SharepointContentItem): string {
  const itemKey = itemKeyWithinSite(sharepointContentItem);
  if (sharepointContentItem.syncSiteId) {
    return `${sharepointContentItem.siteId.value}${KEY_SEPARATOR}${itemKey}`;
  }
  return itemKey;
}

/**
 * Builds a unique hierarchical key for ingestion.
 *
 * Main-site items:        `{siteId}/{itemId}`
 * Subsite items:          `{parentSiteId}/{subsiteId}::{itemId}`
 * Main-site attachments:  `{siteId}/{listId}::{itemId}::{fileName}`
 * Subsite attachments:    `{parentSiteId}/{subsiteId}::{listId}::{itemId}::{fileName}`
 */
export function buildIngestionItemKey(sharepointContentItem: AnySharepointItem): string {
  const itemKey = itemKeyWithinSite(sharepointContentItem);
  if (sharepointContentItem.syncSiteId) {
    return `${sharepointContentItem.syncSiteId.value}/${sharepointContentItem.siteId.value}${KEY_SEPARATOR}${itemKey}`;
  }
  return `${sharepointContentItem.siteId.value}/${itemKey}`;
}

function itemKeyWithinSite(item: AnySharepointItem): string {
  if (item.itemType === 'listItemAttachment') {
    return [item.driveId, item.item.id, item.fileName].join(KEY_SEPARATOR);
  }
  return item.item.id;
}

// Only attachment keys end in `{listId}::{itemId}::{fileName}`: other keys have at most one
// separator, and SharePoint forbids `:` in file names.
const ATTACHMENT_KEY_REGEX = new RegExp(`^(.+${KEY_SEPARATOR}\\d+${KEY_SEPARATOR})([^:]+)$`);

/**
 * Smears the file name of a list item attachment key, which is customer data, and leaves its ids
 * readable. Works for both ingestion and file-diff keys; any other key is returned unchanged.
 */
export function smearContentKey(key: string): string {
  return key.replace(
    ATTACHMENT_KEY_REGEX,
    (_, ids: string, fileName: string) => `${ids}${createSmeared(fileName)}`,
  );
}

/**
 * Extracts a relative path from a SharePoint URL, stripping the managed path and site name prefix.
 *
 * For regular sites (siteName = "SiteName"), strips /{sites|teams}/SiteName.
 * For subsites (siteName = "SiteName/SubSite"), strips /{sites|teams}/SiteName/SubSite.
 *
 * We need to pass siteName because in the url, subsite is indistinguishable from a library. If you
 * have a subsite named SubsiteA and a library called DriveB, the urls will simply be
 * https://tenant.sharepoint.com/{sites|teams}/SiteName/SubsiteA and
 * https://tenant.sharepoint.com/{sites|teams}/SiteName/DriveB with no indication which is which.
 * To distinguish between the two, we need to pass the siteName to the function.
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

/**
 * `siteName` controls how many leading URL segments are stripped. In the subsitesScan flow, pass
 * the **top parent** site's name so that subsite segments are preserved as folders in the
 * hierarchy. Passing the subsite's own name would incorrectly strip it from the resulting path.
 */
export function getUniquePathFromItem(
  item: AnySharepointItem,
  rootPath: Smeared,
  siteName: Smeared,
): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  if (item.itemType === 'listItemAttachment') {
    return createSmeared(`${buildListItemFolderPath(item, rootPath)}/${item.fileName}`);
  }
  const fileUrl = extractFileUrl(item);
  const uniquePath = getRelativeUniquePathFromUrl(fileUrl, siteName);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniquePath}`);
}

/** @see {@link getUniquePathFromItem} for `siteName` semantics. */
export function getUniqueParentPathFromItem(
  item: AnySharepointItem,
  rootPath: Smeared,
  siteName: Smeared,
): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  if (item.itemType === 'listItemAttachment') {
    return createSmeared(buildListItemFolderPath(item, rootPath));
  }
  const fileUrl = extractFileUrl(item);
  const uniqueParentPath = getRelativeUniqueParentPathFromUrl(fileUrl, siteName);

  return createSmeared(`/${normalizeSlashes(rootPath.value)}${uniqueParentPath}`);
}

export function getUniqueListFolderPathFromItem(
  item: ListItemAttachment,
  rootPath: Smeared,
): Smeared {
  assert.ok(rootPath.value, 'rootPath cannot be empty');
  return createSmeared(buildListFolderPath(item, rootPath));
}

// `{rootPath}/{subsite relative path, if any}/{list folder}`.
function buildListFolderPath(item: ListItemAttachment, rootPath: Smeared): string {
  const segments = [normalizeSlashes(rootPath.value)];
  if (item.subsiteRelativePath) {
    segments.push(normalizeSlashes(item.subsiteRelativePath));
  }
  segments.push(item.driveName);
  return `/${segments.filter((segment) => segment.length > 0).join('/')}`;
}

// `{list folder path}/{item folder}`.
function buildListItemFolderPath(item: ListItemAttachment, rootPath: Smeared): string {
  return `${buildListFolderPath(item, rootPath)}/${normalizeSlashes(item.folderPath)}`;
}

function extractFileUrl(item: AnySharepointItem): string {
  if (item.itemType === 'listItemAttachment') {
    return item.attachment.absoluteUrl;
  }
  if (item.itemType === 'driveItem') {
    return item.item.listItem?.webUrl || item.item.webUrl;
  }
  return item.item.webUrl;
}
