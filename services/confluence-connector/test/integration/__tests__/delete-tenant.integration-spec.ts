/**
 * Behavior: tenant deletion (#370).
 *
 * When a tenant's status is set to `deleted` in configuration, the scheduler
 * routes the cron tick to `TenantDeleteService.deleteTenantContent()` instead
 * of `synchronize()`. The deletion flow:
 *
 *  1. Looks up the root scope. If missing, the cleanup is skipped.
 *  2. Reads the root scope's `externalId`. If `null`, cleanup has already run
 *     and the call is a no-op (idempotency marker).
 *  3. Lists child scopes, deletes their content via `getContentIdsByScope` +
 *     `deleteByIds`, then removes the child scopes themselves recursively.
 *  4. Clears the root scope's `externalId` to mark cleanup as complete.
 *
 * The root scope is intentionally preserved so the tenant can be re-activated
 * later without rebuilding its scope tree.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope, uniqueScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('delete tenant', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // The canonical cleanup flow: every child scope and every file owned by
  // those scopes is deleted; the root scope survives with a cleared externalId.
  it('deletes every child scope and file while preserving the root scope', async () => {
    const scenario = defineScenario({
      unique: {
        scopes: [
          // Root scope is owned (externalId set), so the cleanup will run.
          uniqueScope({
            id: 'root-scope-id',
            name: 'Confluence',
            externalId: 'confc:cloud:cloud-1',
          }),
          spaceScope({
            rootScopeId: 'root-scope-id',
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
          spaceScope({
            rootScopeId: 'root-scope-id',
            spaceKey: 'HR',
            spaceId: 'space-hr',
            scopeId: 'scope-hr',
          }),
        ],
        files: [
          pageFile({
            pageId: 'eng-1',
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
          pageFile({
            pageId: 'eng-2',
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
          pageFile({ pageId: 'hr-1', spaceKey: 'HR', spaceId: 'space-hr', scopeId: 'scope-hr' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runDelete();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    // Only the root scope remains, with its externalId cleared as the
    // "cleanup completed" marker.
    expect(state.scopes).toEqual([
      expect.objectContaining({ path: '/Confluence', externalId: null }),
    ]);
    expect(state.files).toEqual([]);
  });

  // The externalId on the root scope acts as the cleanup-completed marker:
  // null after a successful run, set otherwise.
  it('clears the root externalId only after the cleanup succeeds', async () => {
    const scenario = defineScenario({
      unique: {
        scopes: [
          uniqueScope({
            id: 'root-scope-id',
            name: 'Confluence',
            externalId: 'confc:cloud:cloud-1',
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const before = getUniqueState(ctx.unique);
    expect(before.scopes[0]?.externalId).toBe('confc:cloud:cloud-1');

    const result = await ctx.runDelete();

    expect(result).toEqual({ status: 'success' });
    const after = getUniqueState(ctx.unique);
    expect(after.scopes[0]?.externalId).toBeNull();
  });

  // Idempotency: a second delete after a successful one is a no-op. The
  // already-cleared externalId is the signal that there is nothing to clean.
  it('skips deletion when the root externalId is already cleared', async () => {
    const scenario = defineScenario({
      unique: {
        scopes: [
          // externalId is null, signalling a previous successful cleanup.
          uniqueScope({ id: 'root-scope-id', name: 'Confluence', externalId: null }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runDelete();

    expect(result).toEqual({ status: 'skipped', reason: 'already_cleaned_up' });
  });
});
