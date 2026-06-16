/**
 * Behavior: root-scope migration.
 *
 * Operators sometimes need to point an active connector at a different root
 * scope in Unique (for example, when reorganizing the scope hierarchy).
 * Migration is performed by changing `ingestion.scopeId` in tenant configuration.
 *
 * The contract:
 *
 *  - Each connector instance owns at most one root scope, identified by the
 *    expected externalId `confc:<instanceType>:<instanceId>`.
 *  - On the first sync after the configured `rootScopeId` changes, the connector
 *    looks up the previous root by that externalId. If it finds one, it moves the
 *    previous root's child scopes (and their files) under the new root, deletes
 *    the now-empty old root, and claims the externalId on the new root. The sync
 *    then proceeds normally under the new root.
 *  - If the previous root can no longer be found by the externalId (e.g. it was
 *    already cleared by the tenant-deletion flow), there is nothing to migrate:
 *    the connector simply claims the new root. Any orphaned content still under
 *    the old root is left for the operator to clean up.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_NAME } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope, uniqueScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('root scope migration', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // Nothing-to-migrate path: the old root's externalId was already cleared (e.g.
  // by the tenant-deletion flow) before the operator switched `rootScopeId`. The
  // connector cannot find a previous root by the externalId, so it just claims
  // the new root and ingests current content there. Orphaned content still under
  // the old root is left untouched for the operator to clean up.
  it('claims the new root scope and ingests content there after the old root has been cleared', async () => {
    const scenario = defineScenario({
      tenant: {
        // Tenant is now pointed at the new root.
        rootScopeId: 'new-root',
        rootScopeName: 'Confluence v2',
      },
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1', title: 'Fresh content' })],
      },
      unique: {
        scopes: [
          // The old root is still in Unique with its externalId already
          // cleared (the tenant-deletion flow ran before the operator changed
          // the config). Its leftover scope tree is also still there.
          uniqueScope({ id: 'old-root', name: DEFAULT_ROOT_SCOPE_NAME, externalId: null }),
          spaceScope({
            rootScopeId: 'old-root',
            spaceKey: 'LEGACY',
            spaceId: 'space-legacy',
            scopeId: 'scope-legacy',
          }),
          // The new root is fresh. No externalId yet, no children.
          uniqueScope({ id: 'new-root', name: 'Confluence v2', externalId: null }),
        ],
        files: [
          // A leftover file under the old root. Because the old root no longer
          // holds the externalId, migration cannot find it, so this is untouched.
          pageFile({
            pageId: 'legacy-page',
            spaceKey: 'LEGACY',
            spaceId: 'space-legacy',
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);
    const registerContent = vi.spyOn(ctx.unique.ingestion, 'registerContent');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    // Only the genuinely new page is ingested. The leftover content under the
    // old root is never re-ingested: migration does not move or rewrite it, so
    // no ingestion call is made for it.
    const ingestedKeys = registerContent.mock.calls.map((call) => call[0].key);
    expect(ingestedKeys).toEqual(['tenant1/space-1_SP/p1']);

    // The new root has been claimed and now hosts the freshly ingested page.
    const newRoot = state.scopes.find((scope) => scope.id === 'new-root');
    expect(newRoot?.externalId).toBe('confc:cloud:cloud-1');
    expect(newRoot?.path).toBe('/Confluence v2');

    // The space scope was created under the new root.
    expect(state.scopes.find((scope) => scope.path === '/Confluence v2/SP')).toBeDefined();

    // Fresh content was ingested under the new root's space, and the leftover
    // file under the old root is left in place (it was not found for migration).
    expectIngested(state, {
      pages: ['tenant1/space-1_SP/p1', 'tenant1/space-legacy_LEGACY/legacy-page'],
    });

    // The old root and its scope tree are untouched: with its externalId already
    // cleared, the connector never found it, so nothing was migrated or deleted.
    const oldRoot = state.scopes.find((scope) => scope.id === 'old-root');
    expect(oldRoot).toBeDefined();
    expect(oldRoot?.externalId).toBeNull();
    expect(state.scopes.find((scope) => scope.id === 'scope-legacy')).toBeDefined();
  });

  // Migration path: the operator switched `rootScopeId` while the previous root
  // still holds the externalId. On the next sync the connector finds that old
  // root by externalId, moves its child scopes (and their files) under the new
  // root, deletes the now-empty old root, and claims the externalId on the new
  // root. The migrated content moves with its scope and is not re-ingested.
  it('migrates child scopes from the previous root and deletes it when the configured root changes', async () => {
    const scenario = defineScenario({
      tenant: {
        rootScopeId: 'new-root',
        rootScopeName: 'Confluence v2',
      },
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [
          // The previous root still holds the externalId, with a space scope and
          // already-ingested content under it.
          uniqueScope({
            id: 'old-root',
            name: DEFAULT_ROOT_SCOPE_NAME,
            externalId: 'confc:cloud:cloud-1',
          }),
          spaceScope({ rootScopeId: 'old-root', scopeId: 'scope-sp' }),
          // The new (configured) root has no externalId yet.
          uniqueScope({ id: 'new-root', name: 'Confluence v2', externalId: null }),
        ],
        files: [pageFile({ pageId: 'p1', scopeId: 'scope-sp' })],
      },
    });
    ctx = buildScenarioContext(scenario);
    const registerContent = vi.spyOn(ctx.unique.ingestion, 'registerContent');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    // The new root now holds the externalId; the old root was deleted.
    expect(state.scopes.find((scope) => scope.id === 'new-root')?.externalId).toBe(
      'confc:cloud:cloud-1',
    );
    expect(state.scopes.find((scope) => scope.id === 'old-root')).toBeUndefined();

    // The previous root's space scope was reparented under the new root.
    expect(state.scopes.find((scope) => scope.id === 'scope-sp')?.path).toBe('/Confluence v2/SP');

    // The migrated file moved with its scope and is preserved. It is not
    // re-ingested: nothing was registered during the sync.
    expect(registerContent).not.toHaveBeenCalled();
    expectIngested(state, { pages: ['tenant1/space-1_SP/p1'] });
  });
});
