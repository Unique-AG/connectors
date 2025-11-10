import { IngestionMode } from '../constants/ingestion.constants';

export function getBaseUrl(
  ingestionMode: IngestionMode,
  rootScopeName: string | undefined,
  sharepointBaseUrl: string,
): string {
  if (ingestionMode === IngestionMode.Recursive) {
    return rootScopeName || sharepointBaseUrl;
  }
  return sharepointBaseUrl;
}
