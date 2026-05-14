export type LiveCatchupResult =
  | { status: 'completed' | 'skipped' }
  | { status: 'failed'; err: unknown };
