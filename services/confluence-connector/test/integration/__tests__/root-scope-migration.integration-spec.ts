/**
 * Behavior: root-scope migration.
 *
 * Operators sometimes need to point an active connector at a different root
 * scope in Unique. For example, when reorganizing scope hierarchy or moving
 * content out of a deprecated parent. Migration is performed by changing
 * `ingestion.scopeId` in tenant configuration.
 *
 * The contract is intentionally simple:
 *
 *  - Each connector instance owns at most one root scope, identified by the
 *    expected externalId `confc:<instanceType>:<instanceId>`.
 *  - The connector only looks at the configured `rootScopeId`. Old roots
 *    (that the operator has stopped pointing at) are invisible to the sync
 *    and are NOT auto-migrated. The operator decides what to do with their
 *    leftover content.
 *  - Because the expected externalId is a one-per-instance value, switching
 *    to a new root requires the previous root's externalId to be cleared
 *    first (typically via the tenant-deletion flow). If the old root still
 *    holds the externalId, the new sync will fail with a clear conflict.
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

  // Happy path: the operator has cleaned up the old root (its externalId is
  // null) and pointed the tenant at a new root. The connector claims the new
  // root and syncs all current Confluence content under it. Anything still
  // sitting under the old root is left alone. Migration of leftover content
  // is an operator decision, not a sync-time behavior.
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
          // A leftover file under the old root that the operator chose not
          // to clean up. Migration must NOT touch it.
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
    // file under the old root is left in place (migration does not move it).
    expectIngested(state, {
      pages: ['tenant1/space-1_SP/p1', 'tenant1/space-legacy_LEGACY/legacy-page'],
    });

    // Leftover scopes under the old root are untouched. Migration does not
    // auto-move them. The operator owns that decision.
    const oldRoot = state.scopes.find((scope) => scope.id === 'old-root');
    expect(oldRoot).toBeDefined();
    expect(oldRoot?.externalId).toBeNull();
    expect(state.scopes.find((scope) => scope.id === 'scope-legacy')).toBeDefined();
  });

  // Conflict path: the operator pointed the tenant at a new root but forgot
  // to clear the old root's externalId. The expected externalId is therefore
  // already taken, so the new root's claim fails. And the entire sync fails
  // safely without touching any data. The operator gets a clear signal that
  // they must run the tenant-deletion flow against the old root before
  // proceeding.
  it('aborts the sync when the previous root scope still holds the expected externalId', async () => {
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
          // The old root still claims the externalId. Operator forgot to
          // run cleanup before switching.
          uniqueScope({
            id: 'old-root',
            name: DEFAULT_ROOT_SCOPE_NAME,
            externalId: 'confc:cloud:cloud-1',
          }),
          // The new (configured) root has no externalId yet.
          uniqueScope({ id: 'new-root', name: 'Confluence v2', externalId: null }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result.status).toBe('failure');

    const state = getUniqueState(ctx.unique);

    // The old root's externalId was not stolen; it still belongs to it.
    expect(state.scopes.find((scope) => scope.id === 'old-root')?.externalId).toBe(
      'confc:cloud:cloud-1',
    );
    // The new root remains unclaimed. The failed updateExternalId did not
    // partially apply.
    expect(state.scopes.find((scope) => scope.id === 'new-root')?.externalId).toBeNull();

    // No content was ingested.
    expect(state.files).toEqual([]);
  });
});
