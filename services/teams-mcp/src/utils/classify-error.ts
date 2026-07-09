import { GraphError } from '@microsoft/microsoft-graph-client';
import { McpError } from '@modelcontextprotocol/sdk/types.js';

/**
 * Transport-level error codes that mean a request never reached its target / got no response
 * (DNS, connection, socket failures) — as opposed to the server returning an HTTP error.
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
 * True when the error is a raw transport-level failure (DNS resolution, connection, socket)
 * rather than an HTTP response. Operates on the *unwrapped* error and is host-agnostic, so it
 * is only meaningful where the caller already knows the target — e.g. the Graph metrics
 * middleware, which sits inside the Graph client chain and sees the original error before the
 * client wraps it into a `GraphError`. The tool boundary must NOT use this to attribute a
 * fault to Microsoft (the same errnos arise from Postgres and the Unique API); it relies on
 * the error type instead (see `classifyError`).
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
          ` Some of these errors are transient and clear on a retry (for example a rate limit); others are persistent — notably a 500 returned while reading a chat whose messages contain content Graph cannot serialize (such as Loop components or certain cards) recurs on every attempt and will not clear by retrying.`,
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

    // A statusCode below 100 means no HTTP response was received: the Graph client wraps
    // fetch/DNS/socket failures into a GraphError with statusCode -1 (discarding the original
    // errno and host). Because only the Graph client produces GraphError, this is unambiguously
    // a connectivity failure reaching Microsoft Graph — no host inspection needed. Transport
    // failures from Postgres or the Unique API are NOT GraphError, so they never land here.
    if (httpStatus < 100) {
      return {
        fault: 'upstream_network',
        retryable: true,
        message:
          `Could not reach Microsoft Graph (no response — likely a connectivity, DNS or timeout ` +
          `issue between this connector and Microsoft). This is not a defect in your request or ` +
          `this connector. This is usually transient — please retry shortly.`,
      };
    }
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
