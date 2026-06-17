import type { IngestionConfig } from '@unique-ag/unique-api';
import { sortBy } from 'remeda';
import type { FakeUniqueApi } from '../fakes/fake-unique-api';

export interface UniqueScopeState {
  id: string;
  name: string;
  path: string;
  externalId: string | null;
}

export interface UniqueFileState {
  id: string;
  key: string;
  scopeId: string;
  scopePath: string | null;
  byteSize: number;
  mimeType: string;
  metadata: Record<string, string> | null;
  body: Buffer | null;
  bodyText: string | null;
  ingestionConfig: IngestionConfig | null;
}

export interface UniqueState {
  scopes: UniqueScopeState[];
  files: UniqueFileState[];
}

const TEXT_MIME_TYPES = new Set(['text/html', 'text/plain', 'application/json']);

/**
 * Returns a diff-friendly view of the FakeUniqueApi state suitable for
 * `expect(state).toMatchObject(...)` assertions in tests.
 *
 * Sorting is stable (scopes by path, files by key) so assertions are independent
 * of insertion order or sync concurrency.
 */
export function getUniqueState(unique: FakeUniqueApi): UniqueState {
  const scopes = unique.listScopes();
  const scopePathById = new Map(scopes.map((scope) => [scope.id, scope.path]));

  const scopeStates: UniqueScopeState[] = sortBy(
    scopes.map((scope) => ({
      id: scope.id,
      name: scope.name,
      path: scope.path,
      externalId: scope.externalId,
    })),
    (scope) => scope.path,
  );

  const fileStates: UniqueFileState[] = sortBy(
    unique.listFiles().map((file) => ({
      id: file.id,
      key: file.key,
      scopeId: file.ownerId,
      scopePath: scopePathById.get(file.ownerId) ?? null,
      byteSize: file.byteSize,
      mimeType: file.mimeType,
      metadata: file.metadata,
      body: file.body ?? null,
      bodyText: bodyTextOrNull(file.mimeType, file.body),
      ingestionConfig: file.ingestionConfig,
    })),
    (file) => file.key,
  );

  return { scopes: scopeStates, files: fileStates };
}

function bodyTextOrNull(mimeType: string, body: Buffer | undefined): string | null {
  if (!body) {
    return null;
  }
  if (!TEXT_MIME_TYPES.has(mimeType)) {
    return null;
  }
  return body.toString('utf-8');
}
