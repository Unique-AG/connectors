import { createHash } from 'node:crypto';
import type { IngestionConfig } from '@unique-ag/unique-api';
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
  byteSize: number;
  mimeType: string;
  metadata: Record<string, string> | null;
  bodyHash: string | null;
  bodySize: number;
  bodyText: string | null;
  /** Captured `ingestionConfig` (e.g. `jpgReadMode`) from the registerContent call. */
  ingestionConfig: IngestionConfig | null;
}

export interface UniqueState {
  scopes: UniqueScopeState[];
  files: UniqueFileState[];
}

const TEXT_MIME_TYPES = new Set(['text/html', 'text/plain', 'application/json']);
const SMALL_BODY_LIMIT_BYTES = 4 * 1024;

/**
 * Returns a diff-friendly view of the FakeUniqueApi state suitable for
 * `expect(state).toMatchObject(...)` assertions in tests.
 *
 * Sorting is stable (scopes by path, files by key) so assertions are independent
 * of insertion order or sync concurrency.
 */
export function getUniqueState(unique: FakeUniqueApi): UniqueState {
  const scopes = unique.listScopes();
  const scopePathById = buildScopePathIndex(scopes);

  const scopeStates: UniqueScopeState[] = scopes
    .map((scope) => ({
      id: scope.id,
      name: scope.name,
      path: scopePathById.get(scope.id) ?? scope.name,
      externalId: scope.externalId,
    }))
    .sort((a, b) => a.path.localeCompare(b.path));

  const fileStates: UniqueFileState[] = unique
    .listFiles()
    .map((file) => ({
      id: file.id,
      key: file.key,
      byteSize: file.byteSize,
      mimeType: file.mimeType,
      metadata: file.metadata,
      bodyHash: file.body ? sha256(file.body) : null,
      bodySize: file.body?.byteLength ?? 0,
      bodyText: bodyTextOrNull(file.mimeType, file.body),
      ingestionConfig: file.ingestionConfig,
    }))
    .sort((a, b) => a.key.localeCompare(b.key));

  return { scopes: scopeStates, files: fileStates };
}

function buildScopePathIndex(scopes: { id: string; name: string; parentId: string | null }[]) {
  const byId = new Map(scopes.map((scope) => [scope.id, scope]));
  const result = new Map<string, string>();
  for (const scope of scopes) {
    const segments: string[] = [];
    let current: { id: string; name: string; parentId: string | null } | undefined = scope;
    const seen = new Set<string>();
    while (current) {
      if (seen.has(current.id)) {
        break;
      }
      seen.add(current.id);
      segments.unshift(current.name);
      current = current.parentId ? byId.get(current.parentId) : undefined;
    }
    result.set(scope.id, `/${segments.join('/')}`);
  }
  return result;
}

function sha256(buf: Buffer): string {
  return createHash('sha256').update(buf).digest('hex');
}

function bodyTextOrNull(mimeType: string, body: Buffer | undefined): string | null {
  if (!body) {
    return null;
  }
  if (!TEXT_MIME_TYPES.has(mimeType)) {
    return null;
  }
  if (body.byteLength > SMALL_BODY_LIMIT_BYTES) {
    return null;
  }
  return body.toString('utf-8');
}
