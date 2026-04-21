export type EmailDiagnosticEntry = {
  messageId: string;
  fileKey: string;
};

export type SyncDiagnosticsResult = {
  messageIdsSkippedBecauseOfFilters: EmailDiagnosticEntry[];
  messageIdsFoundInMicrosoftButNotFoundInUnique: EmailDiagnosticEntry[];
  messageIdsFoundInUniqueButNotFoundInMicrosoft: EmailDiagnosticEntry[];
};
