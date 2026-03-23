export interface McpErrorMetadata {
  mcpErrorCode?: number;
  retryable?: boolean;
  context?: Record<string, unknown>;
}

export abstract class McpBaseError extends Error {
  public readonly _tag = 'McpFailure' as const;
  public abstract readonly errorCode: string;

  constructor(
    message: string,
    public readonly metadata: McpErrorMetadata = {},
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = this.constructor.name;
  }
}
