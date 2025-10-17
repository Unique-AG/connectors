import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { isDriveItem, isListItem } from '../msgraph/types/type-guards.util';

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
  let itemName: string;

  // we cannot use webUrl for driveItems as they are not using the real path but proxy _layouts
  if (isDriveItem(sharepointContentItem)) {
    itemName = sharepointContentItem.item.name;
  }
  // for listItems we can use directly the webUrl property
  else if (isListItem(sharepointContentItem)) {
    return sharepointContentItem.item.webUrl;
  } else {
    itemName = sharepointContentItem.item.id; // fallback to id
  }

  return buildUrl(sharepointContentItem.siteWebUrl, sharepointContentItem.folderPath, itemName);
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
