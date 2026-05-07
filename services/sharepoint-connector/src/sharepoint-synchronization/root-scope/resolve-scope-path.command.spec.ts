import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../../unique-api/unique-scopes/unique-scopes.types';
import { ResolveScopePathCommand } from './resolve-scope-path.command';

const buildScope = (overrides: Partial<Scope> & Pick<Scope, 'id' | 'name'>): Scope => ({
  parentId: null,
  externalId: null,
  ...overrides,
});

describe('ResolveScopePathCommand', () => {
  let service: ResolveScopePathCommand;
  let getScopeByIdMock: ReturnType<typeof vi.fn>;
  let createScopeAccessesMock: ReturnType<typeof vi.fn>;

  const userId = 'user-123';

  beforeEach(async () => {
    getScopeByIdMock = vi.fn();
    createScopeAccessesMock = vi.fn();

    const { unit } = await TestBed.solitary(ResolveScopePathCommand)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeById: getScopeByIdMock,
        createScopeAccesses: createScopeAccessesMock,
      }))
      .compile();

    service = unit;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns "/scopeName" for a scope with no parent', async () => {
    const root = buildScope({ id: 'scope_root', name: 'Root', parentId: null });

    const result = await service.execute(root, userId);

    expect(result.value).toBe('/Root');
    expect(getScopeByIdMock).not.toHaveBeenCalled();
    expect(createScopeAccessesMock).not.toHaveBeenCalled();
  });

  it('walks up to the root and returns "/A/B/C" for a 3-level chain', async () => {
    const a = buildScope({ id: 'scope_a', name: 'A', parentId: null });
    const b = buildScope({ id: 'scope_b', name: 'B', parentId: 'scope_a' });
    const c = buildScope({ id: 'scope_c', name: 'C', parentId: 'scope_b' });

    getScopeByIdMock.mockImplementation(async (id: string) => {
      if (id === 'scope_a') {
        return a;
      }
      if (id === 'scope_b') {
        return b;
      }
      return null;
    });

    const result = await service.execute(c, userId);

    expect(result.value).toBe('/A/B/C');
    expect(getScopeByIdMock).toHaveBeenCalledWith('scope_b');
    expect(getScopeByIdMock).toHaveBeenCalledWith('scope_a');
  });

  it('grants READ on each ancestor BEFORE calling getScopeById for that ancestor', async () => {
    const a = buildScope({ id: 'scope_a', name: 'A', parentId: null });
    const b = buildScope({ id: 'scope_b', name: 'B', parentId: 'scope_a' });
    const c = buildScope({ id: 'scope_c', name: 'C', parentId: 'scope_b' });

    getScopeByIdMock.mockImplementation(async (id: string) => {
      if (id === 'scope_a') {
        return a;
      }
      if (id === 'scope_b') {
        return b;
      }
      return null;
    });

    await service.execute(c, userId);

    // Each ancestor must be granted READ access strictly before that ancestor is fetched.
    const accessForB = createScopeAccessesMock.mock.calls.findIndex(
      ([scopeId]) => scopeId === 'scope_b',
    );
    const accessForA = createScopeAccessesMock.mock.calls.findIndex(
      ([scopeId]) => scopeId === 'scope_a',
    );
    expect(accessForB).toBeGreaterThanOrEqual(0);
    expect(accessForA).toBeGreaterThanOrEqual(0);

    const accessForBOrder = createScopeAccessesMock.mock.invocationCallOrder[accessForB];
    const accessForAOrder = createScopeAccessesMock.mock.invocationCallOrder[accessForA];

    const getForB = getScopeByIdMock.mock.calls.findIndex(([id]) => id === 'scope_b');
    const getForA = getScopeByIdMock.mock.calls.findIndex(([id]) => id === 'scope_a');
    const getForBOrder = getScopeByIdMock.mock.invocationCallOrder[getForB];
    const getForAOrder = getScopeByIdMock.mock.invocationCallOrder[getForA];

    expect(accessForBOrder).toBeDefined();
    expect(accessForAOrder).toBeDefined();
    expect(getForBOrder).toBeDefined();
    expect(getForAOrder).toBeDefined();

    expect(accessForBOrder as number).toBeLessThan(getForBOrder as number);
    expect(accessForAOrder as number).toBeLessThan(getForAOrder as number);

    // Sanity: the granted-access payload is a READ for the configured user.
    expect(createScopeAccessesMock).toHaveBeenCalledWith('scope_b', [
      { type: 'READ', entityId: userId, entityType: 'USER' },
    ]);
    expect(createScopeAccessesMock).toHaveBeenCalledWith('scope_a', [
      { type: 'READ', entityId: userId, entityType: 'USER' },
    ]);
  });

  it('throws if an ancestor is missing mid-chain', async () => {
    const c = buildScope({ id: 'scope_c', name: 'C', parentId: 'scope_b' });
    getScopeByIdMock.mockResolvedValue(null);

    await expect(service.execute(c, userId)).rejects.toThrow(
      /Parent scope scope_b not found for scope scope_c/,
    );
  });
});
