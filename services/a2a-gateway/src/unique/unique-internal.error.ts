export class UniqueInternalError extends Error {
  public constructor(
    message: string,
    public readonly code:
      | 'UNAUTHORIZED'
      | 'NOT_FOUND'
      | 'CONFLICT'
      | 'UNAVAILABLE'
      | 'INVALID_RESPONSE',
    public readonly retryable: boolean,
  ) {
    super(message);
  }
}
