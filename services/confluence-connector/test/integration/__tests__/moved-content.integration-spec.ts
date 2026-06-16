/**
 * Behavior: how the connector reacts to a `moved` file-diff result.
 *
 * The connector never moves content itself. The move is decided by Unique:
 * `performFileDiff` returns `movedFiles` (a real `FileDiffResponse` category
 * alongside new/updated/deleted) for content Unique recognizes as the same
 * logical resource re-keyed to a new location. This happens in practice when a
 * Confluence page is relocated between spaces, so its content key prefix changes.
 *
 * When Unique reports a file as moved, the connector treats it as a no-op: it
 * records the `moved` diff metric and otherwise leaves the file exactly where it
 * is. A moved file is never re-ingested (no new upload) and never deleted. The
 * sync pipeline enforces this by excluding moved ids from both the set of items
 * it fetches/ingests and the set it deletes.
 *
 * The fake reproduces the same condition Unique detects: the page already exists
 * in Unique under a different key (a different space), and the sync now submits
 * it under the current space's key. Same page id, different location, so the diff
 * reports it as moved.
 *
 * The new / updated / deleted paths are covered by `single-page-sync`,
 * `update-content`, and `delete-content` respectively.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_ID } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('moved content', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // The page lives in space SP now, but Unique still has it under an older space
  // key. The sync submits the same page id under SP, so the diff reports it as
  // moved. The connector records the `moved` metric and leaves the file
  // untouched: still at its old key, same stored body, no delete.
  it('records the moved metric and leaves a moved file untouched', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        // Same page id, but stored under a different space key than the one the
        // sync now uses (SP). That mismatch is what makes the diff see a move.
        files: [pageFile({ pageId: 'p1', spaceKey: 'OLD', body: '<p>Already-ingested body</p>' })],
      },
    });
    ctx = buildScenarioContext(scenario);
    const recordFileDiffEvents = vi.spyOn(ctx.metrics, 'recordFileDiffEvents');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    // The file is preserved verbatim. Not re-ingested under the new key, not deleted.
    const state = getUniqueState(ctx.unique);
    expectIngested(state, { pages: ['tenant1/space-1_OLD/p1'] });
    expectNotIngested(state, { pages: ['tenant1/space-1_SP/p1'] });
    expect(state.files).toHaveLength(1);
    expect(state.files[0]?.bodyText).toBe('<p>Already-ingested body</p>');

    // The move is counted, and nothing was classified as deleted.
    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'moved');
    expect(recordFileDiffEvents).not.toHaveBeenCalledWith(expect.anything(), 'deleted');
  });

  // A move alongside a genuinely new page and a removed page in one sync. The
  // classifier must keep them apart: the moved file is left at its old key, the
  // new page is ingested, and only the removed page is deleted.
  it('distinguishes a move from a new page and a deleted page in the same sync', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'moved' }), page({ id: 'fresh' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        files: [
          // 'moved' already exists under a different space key (relocated to SP).
          pageFile({ pageId: 'moved', spaceKey: 'OLD', body: '<p>Old body</p>' }),
          // 'stale' exists under SP but is no longer in Confluence.
          pageFile({ pageId: 'stale' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);
    const recordFileDiffEvents = vi.spyOn(ctx.metrics, 'recordFileDiffEvents');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expectIngested(state, {
      // moved: untouched at its old key. new: ingested under SP.
      pages: ['tenant1/space-1_OLD/moved', 'tenant1/space-1_SP/fresh'],
    });
    expectNotIngested(state, {
      // moved is not re-ingested under SP, and the stale page is deleted.
      pages: ['tenant1/space-1_SP/moved', 'tenant1/space-1_SP/stale'],
    });

    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'moved');
    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'new');
    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'deleted');
  });
});
