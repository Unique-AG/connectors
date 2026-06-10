export type LiveCatchupResult =
  | { status: 'completed' | 'skipped' }
  | { status: 'failed'; err: unknown };

export type LiveCatchupRoundResult =
  | { status: 'success'; batchProcessingStartedAt: Date }
  | { status: 'no-delegates' }
  | { status: 'failed'; err: unknown };
