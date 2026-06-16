/**
 * Behavior: per-item deletion when source content disappears from Confluence.
 *
 * The file diff returns three categories: new, updated, and deleted. Items that
 * exist in Unique under a space's partial-key prefix but are no longer offered
 * by the discovery pass are deleted from Unique by id. This is what keeps
 * Unique aligned with the source of truth (Confluence) without requiring a
 * full reset of the space.
 *
 * The per-item deletion path is distinct from the per-space deletion path
 * tested in `delete-space.integration-spec.ts`. That one removes whole space
 * scopes when no labeled content remains in the space at all.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { attachment, page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_ID } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { attachmentFile, pageFile, spaceScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('delete content', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // A page existed in Unique from a prior sync but its source page is gone
  // from Confluence. The next sync should detect the gap and delete the file.
  it('removes a file from Unique when its source page is gone from Confluence', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        // Only `keeper` remains in Confluence; `removed` is gone.
        pages: [page({ id: 'keeper', title: 'Still here' })],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        // Both files were ingested by an earlier sync. The keeper's updatedAt
        // matches the page version, so it is a no-op; `removed` has no source
        // and must be deleted.
        files: [pageFile({ pageId: 'keeper' }), pageFile({ pageId: 'removed' })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expectIngested(state, { pages: ['tenant1/space-1_SP/keeper'] });
    expectNotIngested(state, { pages: ['tenant1/space-1_SP/removed'] });
  });

  // A page is still in Confluence but one of its attachments has been removed.
  // The page file stays; the orphaned attachment file is deleted.
  it('removes an attachment file when the attachment no longer exists on the page', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            title: 'Page With An Attachment Removed',
            // The page still has one attachment, `att-keeper`. `att-removed`
            // is no longer on the page.
            attachments: [attachment({ id: 'att-keeper', title: 'keeper.pdf' })],
          }),
        ],
      },
      unique: {
        scopes: [spaceScope({ rootScopeId: DEFAULT_ROOT_SCOPE_ID })],
        files: [
          pageFile({ pageId: 'p1' }),
          attachmentFile({ pageId: 'p1', attachmentId: 'att-keeper' }),
          attachmentFile({ pageId: 'p1', attachmentId: 'att-removed' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expectIngested(state, {
      pages: ['tenant1/space-1_SP/p1'],
      attachments: ['tenant1/space-1_SP/p1::att-keeper'],
    });
    expectNotIngested(state, { attachments: ['tenant1/space-1_SP/p1::att-removed'] });
  });
});
