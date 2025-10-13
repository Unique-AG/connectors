export class FatalPipelineError extends Error {
  public constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'FatalPipelineError';
    this.cause = cause;
  }
}

