import { IngestionMode, PATH_BASED_INGESTION } from '../constants/ingestion.constants';

export function getScopeIdForIngestion(
  ingestionMode: IngestionMode,
  configScopeId: string | undefined,
  contextScopeId: string | undefined,
): string {
  // Recursive Advanced uses dynamically created scope from context
  if (ingestionMode === IngestionMode.RecursiveAdvanced) {
    if (!contextScopeId) {
      throw new Error('scopeId must be set in context for recursive-advanced mode');
    }
    return contextScopeId;
  }

  // Recursive uses PATH-based ingestion
  if (ingestionMode === IngestionMode.Recursive) {
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
  ingestionScopeLocation: string | undefined,
  rootScopeName: string | undefined,
  sharepointBaseUrl: string,
): string {
  if (ingestionMode === IngestionMode.RecursiveAdvanced) {
    return ingestionScopeLocation || '';
  }
  return rootScopeName || sharepointBaseUrl;
}
