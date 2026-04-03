/** Thrown from a tool handler to signal a domain-level tool failure to the MCP framework. */
export class ToolError extends Error {
  public override readonly name = 'ToolError';

  public constructor(message: string) {
    super(message);
  }
}

/** Thrown from a resource handler to signal a domain-level resource failure to the MCP framework. */
export class ResourceError extends Error {
  public override readonly name = 'ResourceError';

  public constructor(message: string) {
    super(message);
  }
}

/** Thrown from a prompt handler to signal a domain-level prompt failure to the MCP framework. */
export class PromptError extends Error {
  public override readonly name = 'PromptError';

  public constructor(message: string) {
    super(message);
  }
}
