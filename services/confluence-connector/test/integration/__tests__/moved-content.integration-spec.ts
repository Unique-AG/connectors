/**
 * Behavior: moved content in the file diff.
 *
 * `performFileDiff` can return a fourth category alongside new/updated/deleted:
 * `movedFiles` — content Unique recognizes as the same logical resource that
 * has been re-keyed to a new location. The connector treats a move as a
 * no-op: it records the `moved` diff metric and otherwise leaves the file
 * exactly where it is. A moved file must never be re-ingested (no new upload)
 * nor deleted.
 *
 * Whether a file is "moved" is decided server-side by Unique, so the in-memory
 * diff cannot derive it; the test injects that verdict via
 * `FakeUniqueApi.simulateMovedFiles`.
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

  // When Unique reports an existing, still-labeled page as moved, the connector
  // records the `moved` metric and leaves the file untouched: same key, same
  // stored body, and no delete.
  it('records the moved metric and leaves a moved file untouched', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        files: [pageFile({ pageId: 'p1', body: '<p>Already-ingested body</p>' })],
      },
    });
    ctx = buildScenarioContext(scenario);
    // The diff item key for a page is its page id (see FileDiffService.buildPageDiffItems).
    ctx.unique.simulateMovedFiles(['p1']);
    const recordFileDiffEvents = vi.spyOn(ctx.metrics, 'recordFileDiffEvents');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    // The file is preserved verbatim — not re-ingested, not deleted.
    const state = getUniqueState(ctx.unique);
    expect(state.files).toHaveLength(1);
    expect(state.files[0]).toMatchObject({
      key: 'tenant1/space-1_SP/p1',
      bodyText: '<p>Already-ingested body</p>',
    });

    // The move is counted, and nothing was classified as deleted.
    expect(recordFileDiffEvents).toHaveBeenCalledWith(1, 'moved');
    expect(recordFileDiffEvents).not.toHaveBeenCalledWith(expect.anything(), 'deleted');
  });
});
