export interface EmailDiagnosticEntry {
  messageId: string;
  fileKey: string;
}

export interface SyncDiagnosticsResult {
  messageIdsSkippedBecauseOfFilters: EmailDiagnosticEntry[];
  messageIdsFoundInMicrosoftButNotFoundInUnique: EmailDiagnosticEntry[];
  messageIdsFoundInUniqueButNotFoundInMicrosoft: EmailDiagnosticEntry[];
}
