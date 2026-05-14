export type LiveCatchupResult =
  | { status: 'completed' | 'skipped' }
  | { status: 'failed'; err: unknown };

export type LiveCathupRoundResult =
  | { status: 'success'; batchProcessingStartedAt: Date }
  | { status: 'failed'; err: unknown };
