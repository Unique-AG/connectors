/**
 * Behavior: Confluence content type handling (#350).
 *
 * Confluence exposes several content kinds: regular pages, blog posts,
 * databases, whiteboards, and embeds. The connector treats them as follows:
 *
 *  - **page**: ingested as HTML.
 *  - **blogpost**: ingested as HTML, identical to page.
 *  - **database / whiteboard / embed**: skipped at ingestion time. These
 *    types do not have meaningful HTML bodies for the AI use case. However,
 *    when one of these is labeled `ai-ingest-all`, the scanner still
 *    traverses its descendants and ingests any page or blog post under it.
 *    This lets editors organize content under a database/whiteboard root
 *    without losing it.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { ContentType } from '../../../src/confluence-api';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_INGEST_ALL_LABEL, DEFAULT_INGEST_LABEL } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('content types', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // Blog posts are ingested with the same key shape and metadata as pages. The
  // type is invisible to Unique once content has been registered.
  it('ingests blog posts the same as pages', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({ id: 'page-1', type: ContentType.PAGE, title: 'A page' }),
          page({ id: 'blog-1', type: ContentType.BLOGPOST, title: 'A blog post' }),
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
        spaces: [space()],
        pages: [
          page({ id: 'real-page', type: ContentType.PAGE }),
          page({ id: 'db', type: ContentType.DATABASE, labels: [DEFAULT_INGEST_LABEL] }),
          page({ id: 'wb', type: ContentType.WHITEBOARD, labels: [DEFAULT_INGEST_LABEL] }),
          page({ id: 'em', type: ContentType.EMBED, labels: [DEFAULT_INGEST_LABEL] }),
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
        spaces: [space()],
        pages: [
          // Three different organizational roots, each a non-page type with
          // ai-ingest-all. None of these roots themselves should appear in
          // Unique.
          page({
            id: 'db-root',
            type: ContentType.DATABASE,
            title: 'Engineering Database',
            labels: [DEFAULT_INGEST_ALL_LABEL],
          }),
          page({
            id: 'wb-root',
            type: ContentType.WHITEBOARD,
            title: 'Roadmap Whiteboard',
            labels: [DEFAULT_INGEST_ALL_LABEL],
          }),
          page({
            id: 'em-root',
            type: ContentType.EMBED,
            title: 'Embedded Dashboard',
            labels: [DEFAULT_INGEST_ALL_LABEL],
          }),
          // Descendants of each root. These should all be ingested.
          page({ id: 'db-child', parentId: 'db-root', type: ContentType.PAGE, labels: [] }),
          page({ id: 'wb-child', parentId: 'wb-root', type: ContentType.BLOGPOST, labels: [] }),
          page({ id: 'em-child', parentId: 'em-root', type: ContentType.PAGE, labels: [] }),
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
