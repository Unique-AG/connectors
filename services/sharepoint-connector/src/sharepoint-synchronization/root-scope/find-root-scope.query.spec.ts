import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import { Smeared } from '../../utils/smeared';
import { createMockSiteConfig } from '../../utils/test-utils/mock-site-config';
import { FindRootScopeQuery } from './find-root-scope.query';

describe('FindRootScopeQuery', () => {
  let service: FindRootScopeQuery;
  let getScopeByExternalIdMock: ReturnType<typeof vi.fn>;
  let listChildrenScopesMock: ReturnType<typeof vi.fn>;

  const siteId = new Smeared('site-123', false);
  const siteName = new Smeared('My Site', false);
  const autoConfig = createMockSiteConfig({
    siteId,
    scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
  });
  const fixedConfig = createMockSiteConfig({
    siteId,
    scopeId: { type: 'fixed', scopeId: 'scope_fixed' },
  });

  beforeEach(async () => {
    getScopeByExternalIdMock = vi.fn().mockResolvedValue(null);
    listChildrenScopesMock = vi.fn().mockResolvedValue([]);

    const { unit } = await TestBed.solitary(FindRootScopeQuery)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeByExternalId: getScopeByExternalIdMock,
        listChildrenScopes: listChildrenScopesMock,
      }))
      .compile();

    service = unit;

    Object.defineProperty(service, 'logger', {
      value: {
        log: vi.fn(),
        error: vi.fn(),
        warn: vi.fn(),
        debug: vi.fn(),
        verbose: vi.fn(),
      },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns null verbatim for fixed configurations without making any calls', async () => {
    const result = await service.execute(fixedConfig, { siteName });

    expect(result).toBeNull();
    expect(getScopeByExternalIdMock).not.toHaveBeenCalled();
    expect(listChildrenScopesMock).not.toHaveBeenCalled();
  });

  it('returns the new-format claimed scope when one exists', async () => {
    const existing = {
      id: 'scope_existing',
      name: 'My Site',
      parentId: 'scope_other_parent',
      externalId: 'spc:site-123/site',
    };
    getScopeByExternalIdMock.mockResolvedValue(existing);

    const result = await service.execute(autoConfig, { siteName });

    expect(result).toBe(existing);
    expect(listChildrenScopesMock).not.toHaveBeenCalled();
  });

  it('returns the legacy-format claimed scope when one exists under the configured parent', async () => {
    const legacyChild = {
      id: 'scope_legacy',
      name: 'Whatever',
      parentId: 'scope_parent',
      externalId: 'spc:site:site-123',
    };
    listChildrenScopesMock.mockResolvedValue([legacyChild]);

    const result = await service.execute(autoConfig, { siteName });

    expect(result).toBe(legacyChild);
  });

  it('returns null when no externalId match is found and siteName is omitted', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_name_only',
        name: 'My Site',
        parentId: 'scope_parent',
        externalId: null,
      },
    ]);

    const result = await service.execute(autoConfig);

    expect(result).toBeNull();
  });

  it('returns null when only a foreign externalId child exists and siteName is omitted', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_foreign',
        name: 'Other',
        parentId: 'scope_parent',
        externalId: 'spc:other-site/site',
      },
    ]);

    const result = await service.execute(autoConfig);

    expect(result).toBeNull();
  });

  it('throws unclaimed_name_match when an unclaimed child shares the configured site name', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_unclaimed',
        name: 'My Site',
        parentId: 'scope_parent',
        externalId: null,
      },
    ]);

    await expect(service.execute(autoConfig, { siteName })).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'unclaimed_name_match',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });
  });

  it('throws foreign_name_match when a foreign-claimed child shares the configured site name', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_foreign',
        name: 'My Site',
        parentId: 'scope_parent',
        externalId: 'spc:other-site/site',
      },
    ]);

    await expect(service.execute(autoConfig, { siteName })).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'foreign_name_match',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });
  });

  it('throws ambiguous_name_match when more than one child shares the configured site name', async () => {
    listChildrenScopesMock.mockResolvedValue([
      { id: 'scope_a', name: 'My Site', parentId: 'scope_parent', externalId: null },
      {
        id: 'scope_b',
        name: 'My Site',
        parentId: 'scope_parent',
        externalId: 'spc:other-site/site',
      },
    ]);

    await expect(service.execute(autoConfig, { siteName })).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'ambiguous_name_match',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });
  });

  it('attaches the Smeared siteName on the thrown error', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_unclaimed',
        name: 'My Site',
        parentId: 'scope_parent',
        externalId: null,
      },
    ]);

    await expect(service.execute(autoConfig, { siteName })).rejects.toMatchObject({
      siteName: expect.objectContaining({ value: 'My Site' }),
    });
  });

  it('skips the name-match step entirely when siteName is omitted', async () => {
    listChildrenScopesMock.mockResolvedValue([
      {
        id: 'scope_unclaimed',
        name: 'Some Name',
        parentId: 'scope_parent',
        externalId: null,
      },
    ]);

    const result = await service.execute(autoConfig);

    expect(result).toBeNull();
  });
});
