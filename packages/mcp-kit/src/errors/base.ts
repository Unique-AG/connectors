/** Structured metadata carried alongside every MCP operational error. */
export interface McpErrorMetadata {
  /** MCP protocol error code to include in the JSON-RPC error response. */
  mcpErrorCode?: number;
  /** Whether the caller may safely retry the operation that produced this error. */
  retryable?: boolean;
  /** Arbitrary key/value pairs for structured logging or debugging. */
  context?: Record<string, unknown>;
}

/**
 * Abstract base class for all expected (operational) MCP errors.
 *
 * The `_tag` discriminant (`'McpFailure'`) lets error-handling code distinguish
 * operational failures from unexpected defects without using `instanceof` chains.
 * Concrete subclasses must provide an `errorCode` string that uniquely identifies
 * the failure kind.
 */
export abstract class McpBaseError extends Error {
  /** Discriminant tag that identifies this as a handled operational failure. */
  public readonly _tag = 'McpFailure' as const;

  /** Machine-readable error code specific to the concrete error subclass. */
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
