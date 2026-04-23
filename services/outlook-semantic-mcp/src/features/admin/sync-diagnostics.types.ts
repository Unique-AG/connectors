export interface EmailDiagnosticEntry {
  messageId: string;
  fileKey: string;
  parentFolderId?: string;
}

export interface SyncDiagnosticsResult {
  messageIdsSkippedBecauseOfFilters: EmailDiagnosticEntry[];
  messageIdsFoundInMicrosoftButNotFoundInUnique: EmailDiagnosticEntry[];
  messageIdsFoundInUniqueButNotFoundInMicrosoft: EmailDiagnosticEntry[];
}
