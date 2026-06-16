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
import { page, space } from '../scenario/confluence-builders';
import { DEFAULT_ROOT_SCOPE_ID, DEFAULT_ROOT_SCOPE_NAME } from '../scenario/defaults';
import { defineScenario } from '../scenario/scenario.builder';
import { uniqueScope } from '../scenario/unique-builders';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { expectIngested } from '../scenario-context/unique-expecter';
import { getUniqueState } from '../scenario-context/unique-state';

describe('root scope ownership', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(() => {
    ctx = undefined;
  });

  // First-sync handshake: the root scope starts unowned and the connector
  // claims it by writing its expected externalId.
  it('claims an unowned root scope on first sync', async () => {
    const scenario = defineScenario({
      // No `unique.scopes` provided. The harness seeds the root scope with
      // externalId=null, which represents an unclaimed root scope.
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
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
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [
          uniqueScope({
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
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
    expectIngested(state, { pages: ['tenant1/space-1_SP/p1'] });
  });

  // Cross-instance safety: another connector instance has already claimed the
  // same root scope. The sync must abort to prevent data conflicts. No files
  // should be written and the externalId must remain unchanged.
  it('aborts the sync when the root scope is owned by a different instance', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1' })],
      },
      unique: {
        scopes: [
          uniqueScope({
            id: DEFAULT_ROOT_SCOPE_ID,
            name: DEFAULT_ROOT_SCOPE_NAME,
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
