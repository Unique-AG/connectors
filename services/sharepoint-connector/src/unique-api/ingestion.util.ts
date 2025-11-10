import { IngestionMode, PATH_BASED_INGESTION } from '../constants/ingestion.constants';

export function getScopeIdForIngestion(
  ingestionMode: IngestionMode,
  configScopeId: string | undefined,
  contextScopeId: string | undefined,
): string {
  // Recursive mode uses dynamically created scope from context or PATH-based ingestion
  if (ingestionMode === IngestionMode.Recursive) {
    if (contextScopeId) {
      return contextScopeId;
    }
    return PATH_BASED_INGESTION;
  }

  // Flat requires configured scopeId
  if (!configScopeId) {
    throw new Error('scopeId must be defined for FLAT ingestion mode');
  }
  return configScopeId;
}

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
