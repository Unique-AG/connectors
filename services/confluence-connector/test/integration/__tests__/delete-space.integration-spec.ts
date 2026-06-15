/**
 * Behavior: per-space deletion when a whole space loses all of its labeled
 * content in Confluence.
 *
 * `ScopeManagementService.cleanupRemovedSpaces` lists the children of the
 * configured root scope and asks: "is this space still discoverable in the
 * current sync?". If a child scope has no corresponding space in the discovery
 * pass, the scope and all its files are deleted by key prefix. This is the
 * heavier counterpart to per-item deletion (see
 * `delete-content.integration-spec.ts`) — it removes whole scope subtrees
 * rather than individual files.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('delete space', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // The Engineering space still has labeled content; HR no longer does.
  // After sync: Engineering survives unchanged, HR scope and all its files
  // are deleted.
  it('deletes a space scope and all its files when the space has no more labeled pages', async () => {
    const scenario = defineScenario({
      confluence: {
        // HR space exists in Confluence but has no labeled pages anymore.
        spaces: [
          space({ id: 'space-eng', key: 'ENG', name: 'Engineering' }),
          space({ id: 'space-hr', key: 'HR', name: 'Human Resources' }),
        ],
        pages: [page({ id: 'eng-1', spaceKey: 'ENG' })],
      },
      unique: {
        scopes: [
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
          pageFile({ pageId: 'eng-1', spaceKey: 'ENG', spaceId: 'space-eng' }),
          pageFile({ pageId: 'hr-1', spaceKey: 'HR', spaceId: 'space-hr' }),
          pageFile({ pageId: 'hr-2', spaceKey: 'HR', spaceId: 'space-hr' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    expect(state.scopes.map((scope) => scope.path).sort()).toEqual([
      '/Confluence',
      '/Confluence/ENG',
    ]);

    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-eng_ENG/eng-1']);
  });

  // The HR space has been entirely deleted on the Confluence side (admin
  // removed the space). At sync time this is indistinguishable from "space
  // exists but has no labeled content" — both produce zero discovered pages
  // for that space — so this exercises the same `cleanupRemovedSpaces` code
  // path as the previous test. It is kept as a separate test on purpose so
  // both real-world operator scenarios (label removal vs space deletion)
  // appear by name in the integration suite and the published docs.
  it('deletes a space scope and all its files when the space itself is gone from Confluence', async () => {
    const scenario = defineScenario({
      confluence: {
        // HR space is no longer present in Confluence at all. Only ENG remains.
        spaces: [space({ id: 'space-eng', key: 'ENG', name: 'Engineering' })],
        pages: [page({ id: 'eng-1', spaceKey: 'ENG' })],
      },
      unique: {
        scopes: [
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
          pageFile({ pageId: 'eng-1', spaceKey: 'ENG', spaceId: 'space-eng' }),
          pageFile({ pageId: 'hr-1', spaceKey: 'HR', spaceId: 'space-hr' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    expect(state.scopes.map((scope) => scope.path).sort()).toEqual([
      '/Confluence',
      '/Confluence/ENG',
    ]);
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-eng_ENG/eng-1']);
  });

  // No-change baseline: the seeded scope and file already match the current
  // state of Confluence, so the sync is a no-op for the space scope and its
  // files (the only state mutation is root-scope ownership being claimed,
  // which is asserted in the single-page sync suite).
  it('preserves a space scope and its files when the space still has labeled content', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: 'root-scope-id' })],
        files: [pageFile({ pageId: 'p1' })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    expect(state.scopes.map((scope) => scope.path).sort()).toEqual([
      '/Confluence',
      '/Confluence/SP',
    ]);
    expect(state.scopes.find((scope) => scope.path === '/Confluence/SP')?.externalId).toBe(
      'confc:tenant1:space-1:SP',
    );
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/p1']);
  });
});
