import { afterEach, describe, expect, it } from 'vitest';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';
import { pageWithAttachmentScenario } from '../scenarios/page-with-attachment.scenario';
import { threePagesOneSpaceScenario } from '../scenarios/three-pages-one-space.scenario';

describe('sync — failure isolation', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // Scenario A: a single page failing to fetch from Confluence must not abort the
  // whole sync. ConfluenceContentFetcher catches the error and returns null;
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

  // Scenario B: when Unique rejects registerContent for one page, IngestionService
  // catches and continues. Because failure happens before contentId is assigned,
  // there is nothing to clean up — the other pages must ingest cleanly.
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

  // Scenario C: when an attachment download fails *after* content was registered
  // in Unique, IngestionService.cleanupFailedRegistration() must delete the
  // half-registered orphan via files.deleteByIds. The HTML page still ingests.
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

    // The HTML page is still ingested; the failed attachment leaves no orphan.
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1']);
  });
});
