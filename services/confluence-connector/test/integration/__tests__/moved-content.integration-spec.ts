/**
 * Behavior: moved content in the file diff.
 *
 * `performFileDiff` can return a fourth category alongside new/updated/deleted:
 * `movedFiles`. Content Unique recognizes as the same logical resource that
 * has been re-keyed to a new location. The connector treats a move as a
 * no-op: it records the `moved` diff metric and otherwise leaves the file
 * exactly where it is. A moved file must never be re-ingested (no new upload)
 * nor deleted.
 *
 * The fake derives this the same way Unique does: the page already exists in
 * Unique under a different key (a different space), and the sync now submits it
 * under the current space's key. Same page id, different location, so the diff
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
    expect(state.files).toHaveLength(1);
    expect(state.files[0]).toMatchObject({
      key: 'tenant1/space-1_OLD/p1',
      bodyText: '<p>Already-ingested body</p>',
    });

    // The move is counted, and nothing was classified as deleted.
    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'moved');
    expect(recordFileDiffEvents).not.toHaveBeenCalledWith(expect.anything(), 'deleted');
  });
});
