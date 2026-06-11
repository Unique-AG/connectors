/**
 * Behavior: root-scope ownership claim and validation (#435).
 *
 * Each connector instance "owns" its configured root scope, identified by
 * `confc:<instanceType>:<instanceId>` written to the root scope's `externalId`.
 * On every sync, `ScopeManagementService.initialize()` does one of three
 * things, depending on the current state of the root scope:
 *
 *  - **Unowned** (`externalId === null`): claim ownership by writing the
 *    expected externalId.
 *  - **Owned by us** (`externalId === expected`): proceed normally.
 *  - **Owned by someone else**: assertion failure that aborts the sync,
 *    preventing two instances from clobbering each other's content.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { aPage, aSpace, aUniqueScope } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

describe('root scope ownership', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // First-sync handshake: the root scope starts unowned and the connector
  // claims it by writing its expected externalId.
  it('claims an unowned root scope on first sync', async () => {
    const scenario = defineScenario({
      // No `unique.scopes` provided — the harness seeds the root scope with
      // externalId=null, which represents an unclaimed root scope.
      confluence: {
        spaces: [aSpace()],
        pages: [aPage({ id: 'p1' })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.scopes.find((scope) => scope.path === '/Confluence')?.externalId).toBe(
      'confc:cloud:cloud-1',
    );
  });

  // Second-sync no-op: the root scope is already owned by this instance.
  // initialize() validates the externalId and proceeds without rewriting it.
  it('proceeds when the root scope is already owned by this instance', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [aPage({ id: 'p1' })],
      },
      unique: {
        scopes: [
          aUniqueScope({
            id: 'root-scope-id',
            name: 'Confluence',
            externalId: 'confc:cloud:cloud-1',
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.scopes.find((scope) => scope.path === '/Confluence')?.externalId).toBe(
      'confc:cloud:cloud-1',
    );
    // The page was still ingested; the ownership check did not block the sync.
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/p1']);
  });

  // Cross-instance safety: another connector instance has already claimed the
  // same root scope. The sync must abort to prevent data conflicts — no files
  // should be written and the externalId must remain unchanged.
  it('aborts the sync when the root scope is owned by a different instance', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [aSpace()],
        pages: [aPage({ id: 'p1' })],
      },
      unique: {
        scopes: [
          aUniqueScope({
            id: 'root-scope-id',
            name: 'Confluence',
            externalId: 'confc:cloud:other-instance',
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result.status).toBe('failure');

    const state = getUniqueState(ctx.unique);
    // Externally-claimed externalId is preserved exactly.
    expect(state.scopes.find((scope) => scope.path === '/Confluence')?.externalId).toBe(
      'confc:cloud:other-instance',
    );
    // No content was written to Unique.
    expect(state.files).toEqual([]);
  });
});
