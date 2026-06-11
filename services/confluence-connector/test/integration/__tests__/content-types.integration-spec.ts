/**
 * Behavior: Confluence content type handling (#350).
 *
 * Confluence exposes several content kinds: regular pages, blog posts,
 * databases, whiteboards, and embeds. The connector treats them as follows:
 *
 *  - **page**: ingested as HTML.
 *  - **blogpost**: ingested as HTML, identical to page.
 *  - **database / whiteboard / embed**: skipped at ingestion time — these
 *    types do not have meaningful HTML bodies for the AI use case. However,
 *    when one of these is labeled `ai-ingest-all`, the scanner still
 *    traverses its descendants and ingests any page or blog post under it.
 *    This lets editors organize content under a database/whiteboard root
 *    without losing it.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { ContentType } from '../../../src/confluence-api';
import { aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('content types', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // Blog posts are ingested with the same key shape and metadata as pages —
  // the type is invisible to Unique once content has been registered.
  it('ingests blog posts the same as pages', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'page-1', type: ContentType.PAGE, title: 'A page' }),
          aPage({ id: 'blog-1', type: ContentType.BLOGPOST, title: 'A blog post' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/blog-1',
      'tenant1/space-1_SP/page-1',
    ]);
  });

  // Database, whiteboard, and embed pages are skipped even when directly
  // labeled with `ai-ingest`. They are not text content and cannot be
  // ingested as HTML.
  it('skips database, whiteboard, and embed content even when labeled', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'real-page', type: ContentType.PAGE }),
          aPage({ id: 'db', type: ContentType.DATABASE, labels: ['ai-ingest'] }),
          aPage({ id: 'wb', type: ContentType.WHITEBOARD, labels: ['ai-ingest'] }),
          aPage({ id: 'em', type: ContentType.EMBED, labels: ['ai-ingest'] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/real-page']);
  });

  // The interesting case: an editor uses a database (or whiteboard, or embed)
  // as the organizational root and labels it `ai-ingest-all`. The root itself
  // is not ingested (it has no usable body), but its page/blogpost descendants
  // ARE traversed and ingested. This lets teams keep working with their
  // preferred Confluence layout without losing content from the AI surface.
  it('ingests page descendants of an ai-ingest-all database/whiteboard/embed root', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          // Three different organizational roots, each a non-page type with
          // ai-ingest-all. None of these roots themselves should appear in
          // Unique.
          aPage({
            id: 'db-root',
            type: ContentType.DATABASE,
            title: 'Engineering Database',
            labels: ['ai-ingest-all'],
          }),
          aPage({
            id: 'wb-root',
            type: ContentType.WHITEBOARD,
            title: 'Roadmap Whiteboard',
            labels: ['ai-ingest-all'],
          }),
          aPage({
            id: 'em-root',
            type: ContentType.EMBED,
            title: 'Embedded Dashboard',
            labels: ['ai-ingest-all'],
          }),
          // Descendants of each root — these should all be ingested.
          aPage({ id: 'db-child', parentId: 'db-root', type: ContentType.PAGE, labels: [] }),
          aPage({ id: 'wb-child', parentId: 'wb-root', type: ContentType.BLOGPOST, labels: [] }),
          aPage({ id: 'em-child', parentId: 'em-root', type: ContentType.PAGE, labels: [] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/db-child',
      'tenant1/space-1_SP/em-child',
      'tenant1/space-1_SP/wb-child',
    ]);
  });
});
