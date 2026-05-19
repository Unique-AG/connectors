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
 * tested in `delete-space.integration-spec.ts` — that one removes whole space
 * scopes when no labeled content remains in the space at all.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  anAttachment,
  anAttachmentFile,
  aPage,
  aPageFile,
  aSpace,
  aSpaceScope,
} from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('delete content', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // A page existed in Unique from a prior sync but its source page is gone
  // from Confluence. The next sync should detect the gap and delete the file.
  it('removes a file from Unique when its source page is gone from Confluence', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        // Only `keeper` remains in Confluence; `removed` is gone.
        pages: [aPage({ id: 'keeper', title: 'Still here' })],
      },
      unique: {
        scopes: [aSpaceScope({ rootScopeId: 'root-scope-id' })],
        // Both files were ingested by an earlier sync. The keeper's updatedAt
        // matches the page version, so it is a no-op; `removed` has no source
        // and must be deleted.
        files: [aPageFile({ pageId: 'keeper' }), aPageFile({ pageId: 'removed' })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/keeper']);
  });

  // A page is still in Confluence but one of its attachments has been removed.
  // The page file stays; the orphaned attachment file is deleted.
  it('removes an attachment file when the attachment no longer exists on the page', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({
            id: 'p1',
            title: 'Page With An Attachment Removed',
            // The page still has one attachment, `att-keeper`. `att-removed`
            // is no longer on the page.
            attachments: [anAttachment({ id: 'att-keeper', title: 'keeper.pdf' })],
          }),
        ],
      },
      unique: {
        scopes: [aSpaceScope({ rootScopeId: 'root-scope-id' })],
        files: [
          aPageFile({ pageId: 'p1' }),
          anAttachmentFile({ pageId: 'p1', attachmentId: 'att-keeper' }),
          anAttachmentFile({ pageId: 'p1', attachmentId: 'att-removed' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/p1',
      'tenant1/space-1_SP/p1::att-keeper',
    ]);
  });
});
