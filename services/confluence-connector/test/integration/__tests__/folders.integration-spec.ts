// Behavior: folders are never fetched, and the pages inside them are ingested at any depth.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContentType } from '../../../src/confluence-api';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_INGEST_ALL_LABEL } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

function folder(id: string, parentId: string, labels: string[] = []) {
  return page({ id, parentId, type: ContentType.FOLDER, body: '', labels });
}

describe('folders', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // root (ai-ingest-all) > folder-a > page-a, folder-b > page-b
  it('ingests pages nested in folders under an ingest-all page without fetching the folders', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({ id: 'root', labels: [DEFAULT_INGEST_ALL_LABEL] }),
          folder('folder-a', 'root'),
          page({ id: 'page-a', parentId: 'folder-a', labels: [] }),
          folder('folder-b', 'folder-a'),
          page({ id: 'page-b', parentId: 'folder-b', labels: [] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);
    const getPageById = vi.spyOn(ctx.confluence, 'getPageById');
    const recordPagesProcessed = vi.spyOn(ctx.metrics, 'recordPagesProcessed');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });
    const state = getUniqueState(ctx.unique);
    expectIngested(state, {
      pages: ['tenant1/space-1_SP/root', 'tenant1/space-1_SP/page-a', 'tenant1/space-1_SP/page-b'],
    });
    expectNotIngested(state, {
      pages: ['tenant1/space-1_SP/folder-a', 'tenant1/space-1_SP/folder-b'],
    });
    expect(state.files.map((file) => file.scopePath)).toEqual([
      '/Confluence/SP',
      '/Confluence/SP',
      '/Confluence/SP',
    ]);
    expect(getPageById.mock.calls.map(([id]) => id).sort()).toEqual(['page-a', 'page-b', 'root']);
    expect(recordPagesProcessed).not.toHaveBeenCalledWith(1, 'failure');
    expect(recordPagesProcessed).not.toHaveBeenCalledWith(1, 'skipped');
  });

  // folder-root (ai-ingest-all) > page-a, folder-b > page-b
  it('ingests the pages inside a folder that carries the ingest-all label', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({ id: 'home', labels: [] }),
          folder('folder-root', 'home', [DEFAULT_INGEST_ALL_LABEL]),
          page({ id: 'page-a', parentId: 'folder-root', labels: [] }),
          folder('folder-b', 'folder-root'),
          page({ id: 'page-b', parentId: 'folder-b', labels: [] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);
    const getPageById = vi.spyOn(ctx.confluence, 'getPageById');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });
    const state = getUniqueState(ctx.unique);
    expectIngested(state, { pages: ['tenant1/space-1_SP/page-a', 'tenant1/space-1_SP/page-b'] });
    expectNotIngested(state, {
      pages: [
        'tenant1/space-1_SP/home',
        'tenant1/space-1_SP/folder-root',
        'tenant1/space-1_SP/folder-b',
      ],
    });
    expect(getPageById.mock.calls.map(([id]) => id).sort()).toEqual(['page-a', 'page-b']);
  });
});
