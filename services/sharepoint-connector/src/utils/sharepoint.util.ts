import assert from 'node:assert';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';

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

// deprecated(24.10.2025): will be reusing it again after ingestion splits url into webUrl and knowledgeBasePathUrl
export function buildKnowledgeBaseUrl(
  sharepointContentItem: SharepointContentItem,
  rootScopeName?: string,
): string {
  // we cannot use webUrl for driveItems as they are not using the real path but proxy _layouts hidden folders in their web url.
  if (sharepointContentItem.itemType === 'driveItem') {
    const url = buildUrl(
      sharepointContentItem.siteWebUrl,
      sharepointContentItem.folderPath,
      sharepointContentItem.item.name,
    );
    const pathWithoutDomain = stripDomain(url);
    return rootScopeName ? `${rootScopeName}/${pathWithoutDomain}` : pathWithoutDomain;
  }

  // for listItems we can use directly the webUrl property
  if (sharepointContentItem.itemType === 'listItem') {
    const url = sharepointContentItem.item.webUrl;
    const pathWithoutDomain = stripDomain(url);
    return rootScopeName ? `${rootScopeName}/${pathWithoutDomain}` : pathWithoutDomain;
  }
  assert.fail('Invalid pipeline item type');
}

function buildUrl(baseUrlRaw: string, folderPathRaw: string, itemName: string): string {
  const baseUrl = baseUrlRaw.replace(/\/$/, '');
  const normalizedFolderPath = normalizeSlashes(folderPathRaw);

  // Handle root folder case
  if (!normalizedFolderPath) {
    return `${baseUrl}/${itemName}`;
  }

  // URL-encode each segment
  const pathSegments = normalizedFolderPath.split('/');
  const encodedSegments = pathSegments.map((segment) => encodeURIComponent(segment));
  const encodedPath = encodedSegments.join('/');

  return `${baseUrl}/${encodedPath}/${itemName}`;
}

/*
 * We are reading the webUrl from item.listItem because it contains the real path to the item.
 * listItem.webUrl example: https://[tenant].sharepoint.com/sites/[site]/[library]/[path]/[filename]
 * item.webUrl example: https://[tenant].sharepoint.com/sites/[site]/_layouts/15/Doc.aspx?sourcedoc=%7B[guid]%7D&file=[filename]&action=edit&mobileredirect=true
 * We are adding ?web=1 to the url to get the web view of the item.
 */
export function getItemUrl(
  sharepointContentItem: SharepointContentItem,
  rootScopeName?: string,
): string {
  let url: string;

  if (sharepointContentItem.itemType === 'driveItem') {
    const baseUrl = sharepointContentItem.item.listItem?.webUrl;
    // if webUrl from listItem is not present we fallback to webUrl from driveItem
    url = baseUrl ? `${baseUrl}?web=1` : sharepointContentItem.item.webUrl;
  } else if (sharepointContentItem.itemType === 'listItem') {
    url = `${sharepointContentItem.item.webUrl}?web=1`;
  } else {
    assert.fail('Invalid pipeline item type');
  }

  // if we do not remove the protocol ingestion will create a scope with the name: my-scope/https://uniqueapp.sharepoint.com instead of my-scope
  const urlWithNoProtocol = stripProtocol(url);

  return rootScopeName ? `${rootScopeName}/${urlWithNoProtocol}` : url;
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

function stripDomain(url: string): string {
  try {
    const urlObj = new URL(url);
    return urlObj.pathname.replace(/^\//, '');
  } catch {
    return url;
  }
}

function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, '');
}
