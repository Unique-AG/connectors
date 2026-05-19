/**
 * Behavior: subtree sync (`ai-ingest-all` label).
 *
 * When a page is labeled with `ai-ingest-all`, the connector ingests that page
 * together with its entire descendant subtree. These tests verify that
 * traversal across single roots, multiple roots, multiple spaces, label
 * combinations, and large descendant counts.
 *
 * Single-page ingestion (the `ai-ingest` label, no descendant fan-out) is
 * covered by `single-page-sync.integration-spec.ts`.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('subtree sync', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // The canonical subtree-sync flow: label the root, get the whole tree.
  it('ingests a labeled root page together with its entire descendant tree', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'root', title: 'Handbook', labels: ['ai-ingest-all'] }),
          aPage({ id: 'child-a', parentId: 'root', title: 'Onboarding' }),
          aPage({ id: 'child-b', parentId: 'root', title: 'Benefits' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.scopes.map((scope) => scope.path)).toEqual(['/Confluence', '/Confluence/SP']);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/child-a',
      'tenant1/space-1_SP/child-b',
      'tenant1/space-1_SP/root',
    ]);
  });

  // Multiple ai-ingest-all roots in the same space — each tree is traversed
  // independently and their results merge into one space scope.
  it('ingests multiple ai-ingest-all roots in the same space', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'root-eng', title: 'Engineering', labels: ['ai-ingest-all'] }),
          aPage({ id: 'eng-1', parentId: 'root-eng', title: 'On-call' }),
          aPage({ id: 'root-hr', title: 'HR', labels: ['ai-ingest-all'] }),
          aPage({ id: 'hr-1', parentId: 'root-hr', title: 'PTO Policy' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.scopes.map((scope) => scope.path)).toEqual(['/Confluence', '/Confluence/SP']);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/eng-1',
      'tenant1/space-1_SP/hr-1',
      'tenant1/space-1_SP/root-eng',
      'tenant1/space-1_SP/root-hr',
    ]);
  });

  // Each space gets its own scope and partial-key namespace, so a multi-space
  // sync produces independent file groups.
  it('ingests across multiple spaces, creating one scope per space', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [
          aSpace({ id: 'space-eng', key: 'ENG', name: 'Engineering' }),
          aSpace({ id: 'space-hr', key: 'HR', name: 'Human Resources' }),
        ],
        pages: [
          aPage({ id: 'eng-root', spaceKey: 'ENG', labels: ['ai-ingest-all'] }),
          aPage({ id: 'eng-child', spaceKey: 'ENG', parentId: 'eng-root' }),
          aPage({ id: 'hr-root', spaceKey: 'HR', labels: ['ai-ingest-all'] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.scopes.map((scope) => scope.path).sort()).toEqual([
      '/Confluence',
      '/Confluence/ENG',
      '/Confluence/HR',
    ]);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-eng_ENG/eng-child',
      'tenant1/space-eng_ENG/eng-root',
      'tenant1/space-hr_HR/hr-root',
    ]);
  });

  // Scale check: an ai-ingest-all root with many descendants must ingest every
  // one of them. This exercises the descendant fan-out (`getDescendantPages`)
  // and pins down the contract that no descendant is silently dropped.
  it('ingests every descendant when an ai-ingest-all root has 50 of them', async () => {
    const DESCENDANT_COUNT = 50;
    const descendants = Array.from({ length: DESCENDANT_COUNT }, (_, i) =>
      aPage({
        id: `child-${String(i + 1).padStart(2, '0')}`,
        parentId: 'root',
        title: `Child ${i + 1}`,
      }),
    );

    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'root', title: 'Big Tree', labels: ['ai-ingest-all'] }),
          ...descendants,
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const fileKeys = state.files.map((file) => file.key).sort();

    expect(fileKeys).toHaveLength(DESCENDANT_COUNT + 1);
    expect(fileKeys).toContain('tenant1/space-1_SP/root');
    expect(fileKeys).toContain('tenant1/space-1_SP/child-01');
    expect(fileKeys).toContain('tenant1/space-1_SP/child-50');
  });

  // `ai-ingest` (single page) and `ai-ingest-all` (full subtree) coexist in one
  // space — their union is what gets ingested, with no double-ingestion.
  it('combines ai-ingest and ai-ingest-all labels in the same space', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [
          aPage({ id: 'standalone', title: 'Release Notes', labels: ['ai-ingest'] }),
          aPage({ id: 'root', title: 'Architecture', labels: ['ai-ingest-all'] }),
          aPage({ id: 'child', parentId: 'root', title: 'Database Schema', labels: [] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/child',
      'tenant1/space-1_SP/root',
      'tenant1/space-1_SP/standalone',
    ]);
  });
});
