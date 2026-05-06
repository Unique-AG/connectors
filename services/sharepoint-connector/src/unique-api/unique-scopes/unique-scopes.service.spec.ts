import { ClientError, type GraphQLResponse } from 'graphql-request';
import { describe, expect, it } from 'vitest';
import { toSafeBulkMoveError } from './bulk-move-error';

// Every message below is copied verbatim from the exception-throwing sites in
// node-ingestion (see monorepo/next/services/node-ingestion/src/scope-operation/
// bulk-move.service.ts and scope-operation-job.service.ts) so the tests fail
// loudly if the server-side contract drifts.
function makeClientError(message: string, code = '400'): ClientError {
  const response = {
    errors: [{ message, extensions: { code } }],
    status: 200,
  } as unknown as GraphQLResponse;
  return new ClientError(response, { query: 'mutation BulkMove { __typename }', variables: {} });
}

describe('toSafeBulkMoveError', () => {
  describe('messages that embed customer content in parentheses', () => {
    it('strips the filename list from "still processing" errors (bulk-move.service.ts:L361)', () => {
      const error = makeClientError(
        'Cannot move: 37 file(s) still processing (morningstar_2024.pdf, file-example_PDF_1MB.pdf, 1750170295_Menu_Booklet_DE-Online.pdf and 34 more). Wait for ingestion to complete.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: 37 file(s) still processing. Wait for ingestion to complete.',
      );
    });

    it('strips duplicate filename lists from "already exist in target folder" errors (bulk-move.service.ts:L177)', () => {
      const error = makeClientError(
        'Cannot move: file(s) with same name already exist in target folder (Secret Report.docx, Budget.xlsx)',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: file(s) with same name already exist in target folder',
      );
    });

    it('strips duplicate folder name lists from "already exist in target location" errors (bulk-move.service.ts:L235)', () => {
      const error = makeClientError(
        'Cannot move: folder(s) with same name already exist in target location (ClientsQ1, ClientsQ2, ClientsQ3 and 5 more)',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: folder(s) with same name already exist in target location',
      );
    });

    it('strips the job id from "active job" errors (scope-operation-job.service.ts:L72)', () => {
      const error = makeClientError(
        'User already has an active job (job_abc123xyz). Please wait for it to complete.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'User already has an active job. Please wait for it to complete.',
      );
    });
  });

  describe('messages without customer content are passed through unchanged', () => {
    it('"At least one of scopeIds or contentIds..." (bulk-move.service.ts:L372)', () => {
      const error = makeClientError(
        'At least one of scopeIds or contentIds must be provided and non-empty',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'At least one of scopeIds or contentIds must be provided and non-empty',
      );
    });

    it('"Files cannot be moved to root level..." (bulk-move.service.ts:L380)', () => {
      const error = makeClientError(
        'Files cannot be moved to root level. Files must have a parent folder.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Files cannot be moved to root level. Files must have a parent folder.',
      );
    });

    it('"Cannot move a folder into itself..." circular reference (bulk-move.service.ts:L410)', () => {
      const error = makeClientError(
        'Cannot move a folder into itself or one of its subfolders. This would create a circular reference.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move a folder into itself or one of its subfolders. This would create a circular reference.',
      );
    });
  });

  describe('permission errors: scope ids are our own identifiers, not customer content, so they pass through', () => {
    it('"...permission to move to destination folder {scopeId}" (bulk-move.service.ts:L72)', () => {
      const error = makeClientError(
        'You do not have permission to move to destination folder scope_uc8sqdlhtt0g62iz8rf1djda',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'You do not have permission to move to destination folder scope_uc8sqdlhtt0g62iz8rf1djda',
      );
    });

    it('"...permission to move from source folder {scopeId}" (bulk-move.service.ts:L87)', () => {
      const error = makeClientError(
        'You do not have permission to move from source folder scope_jclo2kz1gibqfb3vzkm29921',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'You do not have permission to move from source folder scope_jclo2kz1gibqfb3vzkm29921',
      );
    });

    it('"...permission to move files from folder {scopeId}" (bulk-move.service.ts:L124)', () => {
      const error = makeClientError(
        'You do not have permission to move files from folder scope_jd90etny3m0eabchbjk5hwuf',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'You do not have permission to move files from folder scope_jd90etny3m0eabchbjk5hwuf',
      );
    });
  });

  describe('regex edge cases', () => {
    it('preserves the plural "(s)" marker even when there is no trailing paren to strip', () => {
      const error = makeClientError(
        'Cannot move: 1 file(s) still processing. Wait for ingestion to complete.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: 1 file(s) still processing. Wait for ingestion to complete.',
      );
    });

    it('preserves the plural "(s)" marker while stripping a single-filename paren', () => {
      const error = makeClientError(
        'Cannot move: 1 file(s) still processing (only-one.pdf). Wait for ingestion to complete.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: 1 file(s) still processing. Wait for ingestion to complete.',
      );
    });

    it('strips multiple leaky parentheticals in a single message', () => {
      // Hypothetical future shape: both file(s) plural AND two sensitive groups.
      const error = makeClientError(
        'Cannot move: folder(s) (a, b, c) and file(s) (x, y) conflict.',
      );

      expect(toSafeBulkMoveError(error).message).toBe(
        'Cannot move: folder(s) and file(s) conflict.',
      );
    });
  });

  describe('fallbacks', () => {
    it('falls back to a generic message when graphqlErrors is empty, never leaking the request dump', () => {
      const response = {
        errors: undefined,
        status: 400,
      } as unknown as GraphQLResponse;
      const error = new ClientError(response, {
        query: 'mutation { __typename }',
        variables: { secret: 'do-not-leak' },
      });

      const result = toSafeBulkMoveError(error);

      expect(result).toBeInstanceOf(Error);
      expect(result.message).toBe('bulkMove failed with status 400');
      expect(result.message).not.toContain('do-not-leak');
      expect(result.message).not.toContain('{"response"');
    });

    it('normalises non-ClientError rejections without transformation', () => {
      const result = toSafeBulkMoveError('network down');

      expect(result).toBeInstanceOf(Error);
      expect(result.message).toBe('network down');
    });
  });
});
