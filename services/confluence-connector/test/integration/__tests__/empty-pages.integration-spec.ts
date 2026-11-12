// Behavior: an empty page is fetched once per version and ingested after an edit.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('empty pages', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  it('skips an empty page, does not fetch it again while unchanged, and ingests it once edited', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'blank', body: '' }), page({ id: 'filled' })],
      },
    });
    ctx = buildScenarioContext(scenario);
    const getPageById = vi.spyOn(ctx.confluence, 'getPageById');
    const recordPagesProcessed = vi.spyOn(ctx.metrics, 'recordPagesProcessed');

    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expectIngested(getUniqueState(ctx.unique), { pages: ['tenant1/space-1_SP/filled'] });
    expectNotIngested(getUniqueState(ctx.unique), { pages: ['tenant1/space-1_SP/blank'] });
    expect(recordPagesProcessed).toHaveBeenCalledWith(1, 'skipped');
    expect(getPageById.mock.calls.map(([id]) => id).sort()).toEqual(['blank', 'filled']);

    getPageById.mockClear();
    recordPagesProcessed.mockClear();
    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expect(getPageById).not.toHaveBeenCalled();
    expect(recordPagesProcessed.mock.calls).toEqual([[1, 'skipped']]);

    ctx.confluence.updatePage('blank', {
      body: '<p>Now with content</p>',
      versionWhen: '2026-06-01T10:00:00.000Z',
    });
    getPageById.mockClear();
    recordPagesProcessed.mockClear();
    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expectIngested(getUniqueState(ctx.unique), {
      pages: ['tenant1/space-1_SP/blank', 'tenant1/space-1_SP/filled'],
    });
    expect(getPageById.mock.calls).toEqual([['blank']]);
    expect(recordPagesProcessed.mock.calls).toEqual([[1, 'success']]);
  });
});
