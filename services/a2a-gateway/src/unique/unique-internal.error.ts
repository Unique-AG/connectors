export class UniqueInternalError extends Error {
  public constructor(
    message: string,
    public readonly code:
      | 'UNAUTHORIZED'
      | 'NOT_FOUND'
      | 'CONFLICT'
      | 'UNAVAILABLE'
      | 'INVALID_RESPONSE'
      | 'TOO_LARGE',
    public readonly retryable: boolean,
  ) {
    super(message);
  }
}
