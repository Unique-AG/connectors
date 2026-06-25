/**
 * Behavior: a page relocated to a different Confluence space.
 *
 * Confluence content keys are space-scoped (`tenant/{spaceId}_{spaceKey}/{pageId}`)
 * and the file diff runs per space. So when a page moves between spaces there is
 * no single "move" operation: the page is new under the destination space's
 * partial key and deleted under the source space's partial key. The net effect
 * is a delete from the old space plus a fresh ingestion under the new one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_ID } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { pageFile, spaceScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested, expectNotIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('cross-space move', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // `p1` used to live in space A and has been relocated to space B in Confluence;
  // `keeper` stays in A. After the sync: A's diff deletes the stale `p1` (no
  // longer discovered in A) while leaving `keeper` alone, and B's diff ingests
  // `p1` fresh under the new space. The old copy is gone and only the moved page
  // is re-ingested.
  it('deletes the page from its old space and re-ingests it under the new one', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [
          space({ id: 'space-a', key: 'A', name: 'Space A' }),
          space({ id: 'space-b', key: 'B', name: 'Space B' }),
        ],
        pages: [page({ id: 'keeper', spaceKey: 'A' }), page({ id: 'p1', spaceKey: 'B' })],
      },
      unique: {
        scopes: [
          spaceScope({
            rootScopeId: DEFAULT_ROOT_SCOPE_ID,
            spaceKey: 'A',
            spaceId: 'space-a',
            scopeId: 'scope-a',
          }),
        ],
        files: [
          pageFile({ pageId: 'keeper', spaceKey: 'A', spaceId: 'space-a', scopeId: 'scope-a' }),
          // The stale copy of the moved page, still under its old space.
          pageFile({ pageId: 'p1', spaceKey: 'A', spaceId: 'space-a', scopeId: 'scope-a' }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);
    const registerContent = vi.spyOn(ctx.unique.ingestion, 'registerContent');

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    // `keeper` stays in A; `p1` now lives under B. The stale A copy of `p1` is gone.
    expectIngested(state, {
      pages: ['tenant1/space-a_A/keeper', 'tenant1/space-b_B/p1'],
    });
    expectNotIngested(state, { pages: ['tenant1/space-a_A/p1'] });

    // Only the relocated page is ingested under its new space; `keeper` is untouched.
    const ingestedKeys = registerContent.mock.calls.map((call) => call[0].key);
    expect(ingestedKeys).toEqual(['tenant1/space-b_B/p1']);
  });
});
