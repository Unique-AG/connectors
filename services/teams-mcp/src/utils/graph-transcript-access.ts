import { GraphError } from '@microsoft/microsoft-graph-client';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

/** Microsoft Graph `innerError.code` when tenant transcript API access is off. */
export const GRAPH_ACCESS_TO_TRANSCRIPTS_DISABLED = 'GraphAccessToTranscriptsDisabled';

/**
 * Actionable guidance when Graph returns {@link GRAPH_ACCESS_TO_TRANSCRIPTS_DISABLED}.
 * Re-consent will not fix this.
 */
export const GRAPH_TRANSCRIPT_ACCESS_DISABLED_MESSAGE =
  'Microsoft Graph access to meeting transcripts is disabled for this tenant. ' +
  'Entra admin consent alone is not enough — a Teams or Global admin must enable ' +
  'Microsoft Graph access under Teams admin center → Meetings → Meeting settings → ' +
  'Transcript API access (or run: Set-CsTeamsMeetingConfiguration -Identity Global ' +
  '-EnableGraphTranscriptAccess $true). Optionally enable speaker attribution ' +
  '(-EnableAttributedTranscripts $true). After enabling, wait a few minutes, then call ' +
  'start_kb_integration again and confirm with verify_kb_integration_status. ' +
  'Unique cannot enable this setting via OAuth.';

/**
 * Thrown when Graph returns `GraphAccessToTranscriptsDisabled` so MCP clients get a
 * clear JSON-RPC error instead of a generic consent / re-auth hint.
 */
export class GraphTranscriptAccessDisabledException extends McpError {
  public constructor(cause?: string) {
    const message = cause
      ? `${GRAPH_TRANSCRIPT_ACCESS_DISABLED_MESSAGE} (Graph: ${cause})`
      : GRAPH_TRANSCRIPT_ACCESS_DISABLED_MESSAGE;
    super(ErrorCode.InternalError, message);
    this.name = 'GraphTranscriptAccessDisabledException';
  }
}

function getGraphInnerErrorCode(error: GraphError): string | undefined {
  if (typeof error.body !== 'string' || error.body.length === 0) {
    return undefined;
  }

  try {
    const parsed: unknown = JSON.parse(error.body);
    if (typeof parsed !== 'object' || parsed === null) {
      return undefined;
    }

    const innerError = (parsed as { innerError?: unknown }).innerError;
    if (typeof innerError !== 'object' || innerError === null) {
      return undefined;
    }

    const code = (innerError as { code?: unknown }).code;
    return typeof code === 'string' ? code : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Detects the tenant-wide Teams Graph transcript access toggle being off.
 * Prefer `innerError.code`; fall back to status + message when body is missing.
 */
export function isGraphAccessToTranscriptsDisabled(error: unknown): boolean {
  if (!(error instanceof GraphError)) {
    return false;
  }

  if (getGraphInnerErrorCode(error) === GRAPH_ACCESS_TO_TRANSCRIPTS_DISABLED) {
    return true;
  }

  return (
    error.statusCode === 403 &&
    typeof error.message === 'string' &&
    error.message.toLowerCase().includes('graph api access to transcripts is disabled')
  );
}
