import z from 'zod/v4';

export enum GraphErrorCode {
  BadRequest = 'BadRequest',
  Unauthorized = 'Unauthorized',
  Forbidden = 'Forbidden',
  NotFound = 'NotFound',
  Conflict = 'Conflict',
  TooManyRequests = 'TooManyRequests',
  InternalServerError = 'InternalServerError',
  ServiceUnavailable = 'ServiceUnavailable',
  GatewayTimeout = 'GatewayTimeout',
  NetworkError = 'NetworkError',
  ParseError = 'ParseError',
  StreamError = 'StreamError',
  Unknown = 'Unknown',
}

const RETRYABLE_CODES = new Set<GraphErrorCode>([
  GraphErrorCode.TooManyRequests,
  GraphErrorCode.ServiceUnavailable,
  GraphErrorCode.GatewayTimeout,
]);

const STATUS_TO_CODE: Record<number, GraphErrorCode> = {
  400: GraphErrorCode.BadRequest,
  401: GraphErrorCode.Unauthorized,
  403: GraphErrorCode.Forbidden,
  404: GraphErrorCode.NotFound,
  409: GraphErrorCode.Conflict,
  429: GraphErrorCode.TooManyRequests,
  500: GraphErrorCode.InternalServerError,
  503: GraphErrorCode.ServiceUnavailable,
  504: GraphErrorCode.GatewayTimeout,
};

/**
 * The error response body returned by Microsoft Graph API on failure.
 *
 * @see https://learn.microsoft.com/en-us/graph/errors
 */
const GraphErrorBody = z.object({
  error: z
    .object({
      code: z.string().optional(),
      message: z.string().optional(),
      innerError: z
        .object({
          code: z.string().optional(),
          date: z.string().optional(),
          'request-id': z.string().optional(),
          'client-request-id': z.string().optional(),
        })
        .optional(),
    })
    .optional(),
});

export type GraphErrorBody = z.infer<typeof GraphErrorBody>;

export class GraphError extends Error {
  public readonly code: GraphErrorCode;
  public readonly statusCode: number | undefined;
  public readonly requestId: string | undefined;
  public readonly graphErrorBody: GraphErrorBody | undefined;

  public constructor(options: {
    message: string;
    code: GraphErrorCode;
    statusCode?: number;
    requestId?: string;
    graphErrorBody?: GraphErrorBody;
    cause?: unknown;
  }) {
    super(options.message, { cause: options.cause });
    this.name = 'GraphError';
    this.code = options.code;
    this.statusCode = options.statusCode;
    this.requestId = options.requestId;
    this.graphErrorBody = options.graphErrorBody;
  }

  public get isRetryable(): boolean {
    return RETRYABLE_CODES.has(this.code);
  }

  public static fromResponse(status: number, rawBody: unknown, headers: Headers): GraphError {
    const code = STATUS_TO_CODE[status] ?? GraphErrorCode.Unknown;
    const body = GraphErrorBody.safeParse(rawBody).data;
    const requestId =
      headers.get('x-ms-request-id') ?? body?.error?.innerError?.['request-id'] ?? undefined;
    const message = body?.error?.message ?? `Graph API responded with ${status}`;

    return new GraphError({
      message,
      code,
      statusCode: status,
      requestId,
      graphErrorBody: body,
    });
  }
}
