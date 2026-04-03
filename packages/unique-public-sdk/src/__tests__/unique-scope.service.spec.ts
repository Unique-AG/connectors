import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopeService } from '../services/unique-scope.service';
import { UNIQUE_PUBLIC_FETCH } from '../unique-public-sdk.consts';
import { ScopeAccessEntityType, ScopeAccessType } from '../unique-public-sdk.dtos';

const context = describe;

const VALID_SCOPE = {
  id: 'scope-1',
  name: 'test-folder',
  parentId: 'parent-1',
  object: 'folder' as const,
};

const ACCESSES = [
  { entityId: 'user-1', entityType: ScopeAccessEntityType.User, type: ScopeAccessType.Read },
  { entityId: 'group-1', entityType: ScopeAccessEntityType.Group, type: ScopeAccessType.Write },
];

describe('UniqueScopeService', () => {
  let service: UniqueScopeService;
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    mockFetch = vi.fn();
    const { unit } = await TestBed.solitary(UniqueScopeService)
      .mock(UNIQUE_PUBLIC_FETCH)
      .impl(() => mockFetch)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => null }))
      .compile();
    service = unit;
  });

  describe('createScope', () => {
    context('when the API creates a scope successfully', () => {
      beforeEach(() => {
        mockFetch.mockResolvedValue({
          ok: true,
          json: async () => ({ createdFolders: [VALID_SCOPE] }),
        });
      });

      it('returns the first created folder', async () => {
        const result = await service.createScope('parent-1', 'test-folder');

        expect(result).toEqual(VALID_SCOPE);
      });

      it('sends a POST to folder with correct payload', async () => {
        await service.createScope('parent-1', 'test-folder', true);

        expect(mockFetch).toHaveBeenCalledWith(
          'folder',
          expect.objectContaining({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: expect.stringContaining('"parentScopeId":"parent-1"'),
          }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'folder',
          expect.objectContaining({ body: expect.stringContaining('"test-folder"') }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'folder',
          expect.objectContaining({ body: expect.stringContaining('"inheritAccess":true') }),
        );
      });
    });

    context('when the API returns zero created folders', () => {
      it('throws a Zod refinement error', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => ({ createdFolders: [] }) });

        await expect(service.createScope('parent-1', 'test-folder')).rejects.toThrow();
      });
    });

    context('when inheritAccess defaults', () => {
      it('defaults to false', async () => {
        mockFetch.mockResolvedValue({
          ok: true,
          json: async () => ({ createdFolders: [VALID_SCOPE] }),
        });

        await service.createScope('parent-1', 'test-folder');

        expect(mockFetch).toHaveBeenCalledWith(
          'folder',
          expect.objectContaining({ body: expect.stringContaining('"inheritAccess":false') }),
        );
      });
    });
  });

  describe('addScopeAccesses', () => {
    const apiResult = {
      id: 'scope-1',
      name: 'test-folder',
      scopeAccesses: ACCESSES,
      children: [],
      object: 'updateFolderAccessResult' as const,
    };

    context('when adding multiple accesses', () => {
      beforeEach(() => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => apiResult });
      });

      it('sends a PATCH to folder/add-access', async () => {
        await service.addScopeAccesses('scope-1', ACCESSES);

        expect(mockFetch).toHaveBeenCalledWith(
          'folder/add-access',
          expect.objectContaining({ method: 'PATCH' }),
        );
      });

      it('includes all access entries in the payload', async () => {
        await service.addScopeAccesses('scope-1', ACCESSES);

        expect(mockFetch).toHaveBeenCalledWith(
          'folder/add-access',
          expect.objectContaining({ body: expect.stringContaining('"scopeId":"scope-1"') }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'folder/add-access',
          expect.objectContaining({ body: expect.stringContaining('"user-1"') }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'folder/add-access',
          expect.objectContaining({ body: expect.stringContaining('"group-1"') }),
        );
      });

      it('returns the parsed result', async () => {
        const result = await service.addScopeAccesses('scope-1', ACCESSES);

        expect(result.id).toBe('scope-1');
        expect(result.object).toBe('updateFolderAccessResult');
      });
    });
  });
});
