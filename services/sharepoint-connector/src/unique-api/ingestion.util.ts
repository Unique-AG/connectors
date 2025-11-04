import { IngestionMode, PATH_BASED_INGESTION } from '../constants/ingestion.constants';

export function getScopeIdForIngestion(
  ingestionMode: IngestionMode,
  scopeId: string | undefined,
): string {
  if (ingestionMode === IngestionMode.Recursive) {
    return PATH_BASED_INGESTION;
  }
  if (!scopeId) {
    throw new Error('scopeId must be defined for FLAT ingestion mode');
  }
  return scopeId;
}
