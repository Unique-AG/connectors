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

export function buildKnowledgeBaseUrl(sharepointContentItem: SharepointContentItem): string {
  // we cannot use webUrl for driveItems as they are not using the real path but proxy _layouts hidden folders in their web url.
  if (sharepointContentItem.itemType === 'driveItem') {
    return buildUrl(
      sharepointContentItem.siteWebUrl,
      sharepointContentItem.folderPath,
      sharepointContentItem.item.name,
    );
  }

  // for listItems we can use directly the webUrl property
  if (sharepointContentItem.itemType === 'listItem') {
    return sharepointContentItem.item.webUrl;
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
