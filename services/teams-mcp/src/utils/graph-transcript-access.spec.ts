import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it } from 'vitest';
import {
  GRAPH_ACCESS_TO_TRANSCRIPTS_DISABLED,
  GRAPH_TRANSCRIPT_ACCESS_DISABLED_MESSAGE,
  GraphTranscriptAccessDisabledException,
  isGraphAccessToTranscriptsDisabled,
} from './graph-transcript-access';

function graphErrorWithBody(partial: {
  statusCode: number;
  code?: string | null;
  message: string;
  body?: string | null;
}): GraphError {
  const error = new GraphError(partial.statusCode, partial.message);
  error.code = partial.code ?? null;
  error.body = partial.body ?? null;
  return error;
}

describe('graph-transcript-access', () => {
  describe('isGraphAccessToTranscriptsDisabled', () => {
    it('returns true when innerError.code is GraphAccessToTranscriptsDisabled', () => {
      const error = graphErrorWithBody({
        statusCode: 403,
        code: 'Forbidden',
        message: 'Graph API access to transcripts is disabled for this tenant.',
        body: JSON.stringify({
          code: 'Forbidden',
          message: 'Graph API access to transcripts is disabled for this tenant.',
          innerError: { code: GRAPH_ACCESS_TO_TRANSCRIPTS_DISABLED },
        }),
      });

      expect(isGraphAccessToTranscriptsDisabled(error)).toBe(true);
    });

    it('returns true when body is missing but status and message match', () => {
      const error = graphErrorWithBody({
        statusCode: 403,
        code: 'Forbidden',
        message: 'Graph API access to transcripts is disabled for this tenant.',
      });

      expect(isGraphAccessToTranscriptsDisabled(error)).toBe(true);
    });

    it('returns false for other 403 Graph errors', () => {
      const error = graphErrorWithBody({
        statusCode: 403,
        code: 'Forbidden',
        message: 'Access denied',
        body: JSON.stringify({
          code: 'Forbidden',
          message: 'Access denied',
          innerError: { code: 'AccessDenied' },
        }),
      });

      expect(isGraphAccessToTranscriptsDisabled(error)).toBe(false);
    });

    it('returns false for non-GraphError values', () => {
      expect(isGraphAccessToTranscriptsDisabled(new Error('boom'))).toBe(false);
      expect(isGraphAccessToTranscriptsDisabled(null)).toBe(false);
    });
  });

  describe('GraphTranscriptAccessDisabledException', () => {
    it('includes actionable guidance and optional Graph cause', () => {
      const exception = new GraphTranscriptAccessDisabledException(
        'Graph API access to transcripts is disabled for this tenant.',
      );

      expect(exception).toBeInstanceOf(GraphTranscriptAccessDisabledException);
      expect(exception.message).toContain(GRAPH_TRANSCRIPT_ACCESS_DISABLED_MESSAGE);
      expect(exception.message).toContain(
        'Graph API access to transcripts is disabled for this tenant.',
      );
      expect(exception.message).toContain('Unique cannot enable this setting via OAuth');
    });
  });
});
