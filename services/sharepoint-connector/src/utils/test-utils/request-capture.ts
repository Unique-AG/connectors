interface CapturedRequest {
  path: string;
  method: string;
  body: unknown;
  headers: Record<string, string>;
  timestamp: number;
}

interface CapturedGraphQLRequest {
  operationName: string;
  query: string;
  variables: Record<string, unknown>;
}

export class RequestCapture {
  private requests: CapturedRequest[] = [];

  public capture(
    method: string,
    path: string,
    body: unknown,
    headers: Record<string, string>,
  ): void {
    let parsedBody = body;
    if (typeof body === 'string') {
      try {
        parsedBody = JSON.parse(body);
      } catch {
        // Keep as string if not JSON
      }
    } else if (body instanceof Buffer) {
      try {
        parsedBody = JSON.parse(body.toString());
      } catch {
        // Keep as buffer/string if not JSON
      }
    }

    this.requests.push({ method, path, body: parsedBody, headers, timestamp: Date.now() });
  }

  public getGraphQLOperations(operationName?: string): CapturedGraphQLRequest[] {
    return this.requests
      .filter((r) => r.path?.endsWith('/graphql'))
      .map((r) => r.body as CapturedGraphQLRequest)
      .filter((op) => !operationName || op.operationName === operationName);
  }

  public getRestCalls(pathPattern: string): CapturedRequest[] {
    return this.requests.filter((r) => r.path?.includes(pathPattern));
  }

  public getAll(): CapturedRequest[] {
    return [...this.requests];
  }

  public clear(): void {
    this.requests = [];
  }
}
