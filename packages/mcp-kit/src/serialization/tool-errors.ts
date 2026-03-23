export class ToolError extends Error {
  public override readonly name = 'ToolError';

  public constructor(message: string) {
    super(message);
  }
}

export class ResourceError extends Error {
  public override readonly name = 'ResourceError';

  public constructor(message: string) {
    super(message);
  }
}

export class PromptError extends Error {
  public override readonly name = 'PromptError';

  public constructor(message: string) {
    super(message);
  }
}
