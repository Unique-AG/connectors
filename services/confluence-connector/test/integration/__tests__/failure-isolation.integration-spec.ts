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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';
import { pageWithAttachmentScenario } from '../scenarios/page-with-attachment.scenario';

// Confluence has three labeled pages in one space; Unique starts empty. One
// page is mocked to fail per test so we can verify the other two still ingest.
const threePagesOneSpaceScenario = defineScenario({
  confluence: {
    spaces: [space()],
    pages: [
      page({ id: 'p1', title: 'Page One' }),
      page({ id: 'p2', title: 'Page Two' }),
      page({ id: 'p3', title: 'Page Three' }),
    ],
  },
});

describe('failure isolation', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // One page failing to load from Confluence must not stop the whole sync.
  // ConfluenceContentFetcher catches the error and returns null, so the page is
  // skipped and the rest keep going.
  it('continues syncing other pages when one page fails to fetch from Confluence', async () => {
    ctx = buildScenarioContext(threePagesOneSpaceScenario);
    const { confluence } = ctx;
    const fetchPage = confluence.getPageById.bind(confluence);
    vi.spyOn(confluence, 'getPageById').mockImplementation(async (pageId) => {
      if (pageId === 'p2') {
        throw new Error('500 from Confluence');
      }
      return fetchPage(pageId);
    });

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1', 'tenant1/space-1_SP/p3']);
  });

  // When Unique rejects registerContent for one page, IngestionService catches
  // it and moves on. The failure happens before a contentId is assigned, so
  // there is nothing to clean up and the other pages still ingest.
  it('continues syncing when Unique rejects registerContent for one page', async () => {
    ctx = buildScenarioContext(threePagesOneSpaceScenario);
    const { ingestion } = ctx.unique;
    const registerContent = ingestion.registerContent.bind(ingestion);
    vi.spyOn(ingestion, 'registerContent').mockImplementation(async (request) => {
      if (request.key === 'tenant1/space-1_SP/p2') {
        throw new Error('Unique ingestion is down');
      }
      return registerContent(request);
    });

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1', 'tenant1/space-1_SP/p3']);
  });

  // If an attachment download fails *after* its content was registered in
  // Unique, IngestionService.cleanupFailedRegistration() deletes the
  // half-registered file (via files.deleteByIds) so no orphan is left. The HTML
  // page still ingests fine.
  it('cleans up the orphaned content when an attachment download fails mid-ingestion', async () => {
    ctx = buildScenarioContext(pageWithAttachmentScenario);
    // The scenario has a single attachment (att-1), so failing every download
    // is equivalent to failing that one.
    vi.spyOn(ctx.confluence, 'getAttachmentDownloadStream').mockRejectedValue(
      new Error('Network blip during attachment download'),
    );

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual(['tenant1/space-1_SP/p1']);
  });
});
