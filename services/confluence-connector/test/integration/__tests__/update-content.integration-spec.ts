/**
 * Behavior: updating already-ingested content (#347, #368).
 *
 * Once content has been ingested, subsequent syncs reconcile changes through
 * `FileDiffService.computeDiff`, which returns three categories of work:
 *
 *  - **new**: keys submitted that don't exist in Unique yet.
 *  - **updated**: keys that exist in Unique with an older `updatedAt` than the
 *    current page's `versionWhen`.
 *  - **deleted**: keys that exist in Unique but were not submitted.
 *
 * This file pins down the two interesting update paths:
 *
 *  1. The simple in-place update. A page's content changed; the file in
 *     Unique is rewritten under the same key.
 *  2. The mass-replacement carve-out. Every existing key is gone and an
 *     entirely new set of keys takes its place. Without protection this would
 *     trip the `validateNoAccidentalFullDeletion` safety net; the carve-out
 *     allows it through (with a warning) when no submitted key overlaps a
 *     deleted key, treating it as a legitimate republication rather than a
 *     bug.
 *
 * Initial ingestion (the diff's `new` path) is covered by
 * `single-page-sync.integration-spec.ts` and `subtree-sync.integration-spec.ts`.
 * The `deleted` path is covered by `delete-content.integration-spec.ts`.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_ID } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

const OLD_VERSION = '2026-01-01T00:00:00.000Z';
const NEW_VERSION = '2026-05-01T10:00:00.000Z';

describe('update content', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // Per-key update path: same page id, newer version. The file is rewritten
  // in place. Its key remains the same and its body changes to reflect the
  // new Confluence content.
  it('updates a file in place when its source page version has advanced', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            body: '<p>Updated content</p>',
            versionWhen: NEW_VERSION,
          }),
        ],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        // Same key, but seeded with an older updatedAt so the diff returns it
        // as `updated`.
        files: [
          pageFile({
            pageId: 'p1',
            body: '<p>Stale content</p>',
            updatedAt: OLD_VERSION,
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expectIngested(state, { pages: ['tenant1/space-1_SP/p1'] });
    expect(state.files).toHaveLength(1);
    expect(state.files[0]?.bodyText).toBe('<p>Updated content</p>');
  });

  // Full-replacement carve-out: an editor archived old pages (p1, p2) and
  // republished new ones (p3, p4) with fresh page IDs. Every existing key
  // would be deleted, but every key is also being replaced by a non-
  // overlapping new one. A legitimate republication, not a bug. The guard
  // logs a warning and lets the sync proceed.
  it('allows a full replacement when every old key is replaced by a non-overlapping new key', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p3', title: 'New page A' }), page({ id: 'p4', title: 'New page B' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        files: [pageFile({ pageId: 'p1' }), pageFile({ pageId: 'p2' })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expectIngested(state, {
      pages: ['tenant1/space-1_SP/p3', 'tenant1/space-1_SP/p4'],
    });
    expectNotIngested(state, {
      pages: ['tenant1/space-1_SP/p1', 'tenant1/space-1_SP/p2'],
    });
  });

  // The other side of the carve-out: the guard aborts when a sync would delete
  // every file in a space without ingesting any replacement. Here the only
  // discovered page (p1) already lives in Unique under a different space key, so
  // the diff classifies it as a move-in rather than a new file. The space's one
  // remaining file (stale) is no longer in Confluence and would be deleted. That
  // is 100% of the space wiped with zero new content, which trips
  // validateNoAccidentalFullDeletion. The whole sync fails and nothing is
  // deleted.
  it('aborts the sync when a diff would delete every file in a space with no new content', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        files: [
          // p1 already exists under a different space key, so it diffs as a move.
          pageFile({ pageId: 'p1', spaceKey: 'OLD' }),
          // The only file under the current space (SP) is gone from Confluence,
          // so the diff would delete it: every file in SP, with nothing new.
          pageFile({ pageId: 'stale' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result.status).toBe('failure');

    // The guard aborted before the deletion phase, so both files are preserved.
    const state = getUniqueState(ctx.unique);
    expectIngested(state, {
      pages: ['tenant1/space-1_OLD/p1', 'tenant1/space-1_SP/stale'],
    });
  });
});
