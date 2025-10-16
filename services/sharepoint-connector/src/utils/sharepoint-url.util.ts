import type { PipelineItem } from '../msgraph/types/pipeline-item.interface';
import { isDriveItem, isListItem } from '../msgraph/types/type-guards.util';

/**
 * Builds the path of the item in knowledge base
 */
export function buildKnowledgeBaseUrl(pipelineItem: PipelineItem): string {
  let itemName: string;

  // we cannot use webUrl for driveItems as they are not using the real path but proxy _layouts
  if (isDriveItem(pipelineItem)) {
    itemName = pipelineItem.item.name;
  }
  // for listItems we can use directly the webUrl property
  else if (isListItem(pipelineItem)) {
    return pipelineItem.item.webUrl;
  } else {
    itemName = pipelineItem.item.id; // fallback to id
  }

  return buildUrl(pipelineItem.siteWebUrl, pipelineItem.folderPath, itemName);
}

function buildUrl(baseUrlRaw: string, folderPathRaw: string, itemName: string): string {
  // Normalize base URL by removing trailing slash
  const baseUrl = baseUrlRaw.replace(/\/$/, '');

  // Ensure folder path starts with slash
  const normalizedFolderPath = folderPathRaw.startsWith('/') ? folderPathRaw : `/${folderPathRaw}`;

  // Handle root folder case
  if (normalizedFolderPath === '/') {
    return `${baseUrl}/${itemName}`;
  }

  // Remove leading slash, URL-encode each segment
  const pathSegments = normalizedFolderPath.substring(1).split('/');
  const encodedSegments = pathSegments.map((segment) => encodeURIComponent(segment));
  const encodedPath = `/${encodedSegments.join('/')}`;

  return `${baseUrl}${encodedPath}/${itemName}`;
}
