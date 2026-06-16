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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_ROOT_SCOPE_ID, DEFAULT_ROOT_SCOPE_NAME } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope, uniqueScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('delete tenant', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
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
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
            externalId: 'confc:cloud:cloud-1',
          }),
          spaceScope({
            rootScopeId: DEFAULT_ROOT_SCOPE_ID,
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
          spaceScope({
            rootScopeId: DEFAULT_ROOT_SCOPE_ID,
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
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
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

  // Resumability: a run that fails partway must leave the externalId set so the
  // next run knows there is still content to clean. Here the first run deletes
  // the space's content but fails to delete the child scope, so the marker
  // stays. A second run finds nothing left to delete, removes the now-empty
  // child scope, and only then clears the marker.
  it('keeps the externalId after a failed run and clears it on a successful retry', async () => {
    const scenario = defineScenario({
      unique: {
        scopes: [
          uniqueScope({
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
            externalId: 'confc:cloud:cloud-1',
          }),
          spaceScope({
            rootScopeId: DEFAULT_ROOT_SCOPE_ID,
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
        ],
        files: [
          pageFile({
            pageId: 'eng-1',
            spaceKey: 'ENG',
            spaceId: 'space-eng',
            scopeId: 'scope-eng',
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    // Fail the first child-scope deletion, then let subsequent calls through.
    const deleteScope = ctx.unique.scopes.delete.bind(ctx.unique.scopes);
    let attempts = 0;
    vi.spyOn(ctx.unique.scopes, 'delete').mockImplementation(async (scopeId, options) => {
      attempts++;
      if (attempts === 1) {
        throw new Error('Transient failure deleting child scope');
      }
      return deleteScope(scopeId, options);
    });

    // First run fails. The marker must survive so the cleanup can be retried.
    const firstResult = await ctx.runDelete();
    expect(firstResult.status).toBe('failure');

    const afterFailure = getUniqueState(ctx.unique);
    expect(afterFailure.scopes.find((scope) => scope.path === '/Confluence')?.externalId).toBe(
      'confc:cloud:cloud-1',
    );

    // Second run finds the leftover scope, deletes it, and clears the marker.
    const secondResult = await ctx.runDelete();
    expect(secondResult).toEqual({ status: 'success' });

    const afterSuccess = getUniqueState(ctx.unique);
    expect(afterSuccess.scopes).toEqual([
      expect.objectContaining({ path: '/Confluence', externalId: null }),
    ]);
    expect(afterSuccess.files).toEqual([]);
  });

  // Idempotency: a second delete after a successful one is a no-op. The
  // already-cleared externalId is the signal that there is nothing to clean.
  it('skips deletion when the root externalId is already cleared', async () => {
    const scenario = defineScenario({
      unique: {
        scopes: [
          // externalId is null, signalling a previous successful cleanup.
          uniqueScope({
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
            externalId: null,
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runDelete();

    expect(result).toEqual({ status: 'skipped', reason: 'already_cleaned_up' });
  });
});
