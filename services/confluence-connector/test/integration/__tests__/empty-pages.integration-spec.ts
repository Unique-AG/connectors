// Behavior: an empty page is skipped on every sync and ingested once it has content.
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

  it('skips an empty page until it is edited, then ingests it', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'blank', body: '' }), page({ id: 'filled' })],
      },
    });
    ctx = buildScenarioContext(scenario);
    const recordPagesProcessed = vi.spyOn(ctx.metrics, 'recordPagesProcessed');

    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expectIngested(getUniqueState(ctx.unique), { pages: ['tenant1/space-1_SP/filled'] });
    expectNotIngested(getUniqueState(ctx.unique), { pages: ['tenant1/space-1_SP/blank'] });
    expect(recordPagesProcessed).toHaveBeenCalledWith(1, 'skipped');

    recordPagesProcessed.mockClear();
    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expectNotIngested(getUniqueState(ctx.unique), { pages: ['tenant1/space-1_SP/blank'] });
    expect(recordPagesProcessed.mock.calls).toEqual([[1, 'skipped']]);

    ctx.confluence.updatePage('blank', {
      body: '<p>Now with content</p>',
      versionWhen: '2026-06-01T10:00:00.000Z',
    });
    recordPagesProcessed.mockClear();
    expect(await ctx.runSync()).toEqual({ status: 'success' });
    expectIngested(getUniqueState(ctx.unique), {
      pages: ['tenant1/space-1_SP/blank', 'tenant1/space-1_SP/filled'],
    });
    expect(recordPagesProcessed.mock.calls).toEqual([[1, 'success']]);
  });
});
