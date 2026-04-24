export const DeleteSkipReason = {
  ScanInProgress: 'scan_in_progress',
  RootScopeNotFound: 'root_scope_not_found',
  AlreadyCleanedUp: 'already_cleaned_up',
} as const;
export type DeleteSkipReason = (typeof DeleteSkipReason)[keyof typeof DeleteSkipReason];

export type DeleteResult =
  | { status: 'success' }
  | { status: 'skipped'; reason: DeleteSkipReason }
  | { status: 'failure'; failures: number };
