import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';

/**
 * Builds the path of the file in knowledge base
 */
export function buildKnowledgeBaseUrl(file: EnrichedDriveItem): string {
  // 1. Normalize base URL by removing trailing slash
  const baseUrl = file.siteWebUrl.replace(/\/$/, '');

  // 2. Ensure folder path starts with slash for consistent processing
  const normalizedFolderPath = file.folderPath.startsWith('/') ? file.folderPath : `/${file.folderPath}`;

  // 3. Handle root folder case (empty folder path)
  if (normalizedFolderPath === '/') {
    return `${baseUrl}/${file.name}`;
  }

  // 4. Remove leading slash, URL-encode each folder segment, then add back leading slash
  const pathSegments = normalizedFolderPath.substring(1).split('/');
  const encodedSegments = pathSegments.map(segment => encodeURIComponent(segment));
  const encodedPath = '/' + encodedSegments.join('/');

  return `${baseUrl}${encodedPath}/${file.name}`;
}
