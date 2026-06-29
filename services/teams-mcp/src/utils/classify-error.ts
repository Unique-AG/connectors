import { GraphError } from '@microsoft/microsoft-graph-client';
import { McpError } from '@modelcontextprotocol/sdk/types.js';

/**
 * Transport-level error codes that mean we could not reach Microsoft Graph at all
 * (DNS, connection, socket failures) — as opposed to Microsoft returning an HTTP error.
 *
 * Mirrors the retryable set used by the SharePoint connector's undici dispatcher
 * (`sharepoint-rest-http.service.ts`), plus `EAI_AGAIN` / `UND_ERR_CONNECT_TIMEOUT`
 * observed in teams-mcp production logs.
 */
const UPSTREAM_NETWORK_CODES = new Set([
  'EAI_AGAIN',
  'ENOTFOUND',
  'ECONNRESET',
  'ECONNREFUSED',
  'ETIMEDOUT',
  'ENETUNREACH',
  'ENETDOWN',
  'EHOSTUNREACH',
  'EPIPE',
  'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_SOCKET',
]);

/**
 * The party at fault for a failed operation.
 * - `upstream_microsoft` — Microsoft Graph returned 429 or 5xx (their server erred).
 * - `upstream_network`    — we could not reach Microsoft Graph (connectivity / DNS).
 * - `client_request`      — Graph rejected our request with a 4xx (bad input / no access).
 * - `auth`                — Microsoft rejected the request as unauthenticated (401).
 * - `unknown`             — anything else; left to existing handling.
 */
export type ErrorFault =
  | 'upstream_microsoft'
  | 'upstream_network'
  | 'client_request'
  | 'auth'
  | 'unknown';

export interface ClassifiedError {
  fault: ErrorFault;
  httpStatus?: number;
  graphCode?: string;
  requestId?: string;
  retryable: boolean;
  message: string;
}

/**
 * True when the error is a transport-level failure to reach Microsoft Graph
 * (DNS resolution, connection, socket) rather than an HTTP response from Graph.
 *
 * undici wraps these in a `TypeError: fetch failed` whose `.cause` carries the
 * original `NodeJS.ErrnoException` (`cause.code`), so we check both levels.
 */
export function isUpstreamNetworkError(error: unknown): boolean {
  if (error instanceof Error && error.message === 'fetch failed') {
    return true;
  }
  const errno = error as NodeJS.ErrnoException | undefined;
  const cause = errno?.cause as NodeJS.ErrnoException | undefined;
  const code = errno?.code ?? cause?.code;
  return code !== undefined && UPSTREAM_NETWORK_CODES.has(code);
}

/**
 * Classify an error thrown from a tool handler so it can be attributed honestly to
 * the consumer: Microsoft's fault, the network's fault, or our/the user's request.
 */
export function classifyError(error: unknown): ClassifiedError {
  if (error instanceof GraphError) {
    const httpStatus = error.statusCode;
    const graphCode = error.code ?? undefined;
    const requestId = error.requestId ?? undefined;

    if (httpStatus === 429 || (httpStatus >= 500 && httpStatus <= 599)) {
      return {
        fault: 'upstream_microsoft',
        httpStatus,
        graphCode,
        requestId,
        retryable: true,
        message:
          `Microsoft Graph returned a server-side error (HTTP ${httpStatus}` +
          (graphCode ? `, code: ${graphCode}` : '') +
          `). This is a fault on Microsoft's side, not a problem with your request or this connector.` +
          (requestId
            ? ` Microsoft request id: ${requestId} (provide this to Microsoft support).`
            : '') +
          ` This is usually transient — please retry shortly.`,
      };
    }

    if (httpStatus === 401) {
      return {
        fault: 'auth',
        httpStatus,
        graphCode,
        requestId,
        retryable: false,
        message:
          `Microsoft rejected the request as unauthenticated (HTTP 401` +
          (graphCode ? `, code: ${graphCode}` : '') +
          `). Your Microsoft session may have expired — please re-authenticate your Microsoft account.`,
      };
    }

    if (httpStatus >= 400 && httpStatus <= 499) {
      return {
        fault: 'client_request',
        httpStatus,
        graphCode,
        requestId,
        retryable: false,
        message:
          `Microsoft Graph rejected the request (HTTP ${httpStatus}` +
          (graphCode ? `, code: ${graphCode}` : '') +
          `). The identifiers or parameters provided may be invalid, or the account may lack access to this resource. Double-check the inputs (for example, list the available chats/teams to obtain a valid id).`,
      };
    }
  }

  if (isUpstreamNetworkError(error)) {
    const errno = error as NodeJS.ErrnoException;
    const cause = errno.cause as NodeJS.ErrnoException | undefined;
    const code = errno.code ?? cause?.code;
    return {
      fault: 'upstream_network',
      retryable: true,
      message:
        `Could not reach Microsoft Graph` +
        (code ? ` (network error: ${code})` : ` (network error)`) +
        `. This is a connectivity or DNS problem between this connector and Microsoft, not a defect in your request or this connector. This is usually transient — please retry shortly.`,
    };
  }

  return {
    fault: 'unknown',
    retryable: false,
    message: error instanceof Error ? error.message : String(error),
  };
}

/**
 * Rewrite an upstream failure into a clearly-attributed `Error` so the MCP module
 * surfaces the attributed text to the consumer as an `isError` tool result.
 *
 * - `McpError` (e.g. {@link MicrosoftReauthRequiredException}) is returned unchanged so
 *   the module re-throws it as a JSON-RPC error and the existing reauth flow is preserved.
 * - `unknown` faults return the original error unchanged so we never mask non-upstream bugs.
 * - Everything else returns a new `Error` carrying the attributed message.
 */
export function toAttributedError(error: unknown): unknown {
  if (error instanceof McpError) {
    return error;
  }

  const classified = classifyError(error);
  if (classified.fault === 'unknown') {
    return error;
  }

  return new Error(classified.message);
}
