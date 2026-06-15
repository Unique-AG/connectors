/**
 * Behavior: failure isolation.
 *
 * A single failing page or attachment must never abort the whole sync. The
 * connector catches per-item errors at well-defined boundaries (content fetch,
 * content registration, attachment download), records the failure, and
 * continues with the rest of the work. When a registration succeeds but a
 * subsequent step fails, the half-registered content is cleaned up so Unique
 * is never left with orphans.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';
import { pageWithAttachmentScenario } from '../scenarios/page-with-attachment.scenario';
import { threePagesOneSpaceScenario } from '../scenarios/three-pages-one-space.scenario';

describe('failure isolation', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // A single page failing to fetch from Confluence must not abort the whole
  // sync. ConfluenceContentFetcher catches the error and returns null;
  // synchronize() records the page as skipped and continues with the rest.
  it('continues syncing other pages when one page fails to fetch from Confluence', async () => {
    ctx = buildScenarioContext(threePagesOneSpaceScenario);
    ctx.confluence.failOnGetPageById('p2', new Error('500 from Confluence'));

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1', 'tenant1/space-1_SP/p3']);
  });

  // When Unique rejects registerContent for one page, IngestionService catches
  // and continues. Because failure happens before contentId is assigned, there
  // is nothing to clean up — the other pages must ingest cleanly.
  it('continues syncing when Unique rejects registerContent for one page', async () => {
    ctx = buildScenarioContext(threePagesOneSpaceScenario);
    ctx.unique.failOnRegisterContent(
      'tenant1/space-1_SP/p2',
      new Error('Unique ingestion is down'),
    );

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1', 'tenant1/space-1_SP/p3']);
  });

  // When an attachment download fails *after* content was registered in Unique,
  // IngestionService.cleanupFailedRegistration() must delete the half-registered
  // orphan via files.deleteByIds. The HTML page still ingests; the failed
  // attachment leaves no orphan.
  it('cleans up the orphaned content when an attachment download fails mid-ingestion', async () => {
    ctx = buildScenarioContext(pageWithAttachmentScenario);
    ctx.confluence.failOnGetAttachmentDownloadStream(
      'att-1',
      new Error('Network blip during attachment download'),
    );

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1']);
  });
});
