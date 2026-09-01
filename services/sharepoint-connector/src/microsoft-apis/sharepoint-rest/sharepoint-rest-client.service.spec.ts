import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createSmeared } from '../../utils/smeared';
import {
  PrincipalType,
  SHAREPOINT_REST_PAGE_SIZE,
  SharepointRestClientService,
  type SiteGroupMembership,
} from './sharepoint-rest-client.service';
import { SharepointRestHttpService } from './sharepoint-rest-http.service';

function createMembership(id: number): SiteGroupMembership {
  return {
    Id: id,
    PrincipalType: PrincipalType.User,
    LoginName: `i:0#.f|membership|user${id}@example.com`,
    Email: `user${id}@example.com`,
    Title: `User ${id}`,
  };
}

describe('SharepointRestClientService', () => {
  let service: SharepointRestClientService;
  let requestBatch: ReturnType<typeof vi.fn>;

  const siteName = createSmeared('Contoso');
  const managedPath = 'sites' as const;

  beforeEach(async () => {
    requestBatch = vi.fn();

    const { unit } = await TestBed.solitary(SharepointRestClientService)
      .mock(SharepointRestHttpService)
      .impl(() => ({ requestBatch }))
      .compile();
    service = unit;
  });

  it('fetches a single page when a group has fewer members than the page size', async () => {
    const members = [createMembership(1), createMembership(2)];
    requestBatch.mockResolvedValueOnce([{ value: members }]);

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12']);

    expect(requestBatch).toHaveBeenCalledOnce();
    expect(requestBatch).toHaveBeenCalledWith(siteName, managedPath, [
      `/sitegroups/getById(12)/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=0`,
    ]);
    expect(result).toEqual({ '12': members });
  });

  it('pages until every group membership is fetched', async () => {
    const firstPage = Array.from({ length: SHAREPOINT_REST_PAGE_SIZE }, (_, index) =>
      createMembership(index + 1),
    );
    const secondPage = [createMembership(SHAREPOINT_REST_PAGE_SIZE + 1)];
    requestBatch
      .mockResolvedValueOnce([{ value: firstPage }])
      .mockResolvedValueOnce([{ value: secondPage }]);

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12']);

    expect(requestBatch).toHaveBeenCalledTimes(2);
    expect(requestBatch).toHaveBeenNthCalledWith(1, siteName, managedPath, [
      `/sitegroups/getById(12)/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=0`,
    ]);
    expect(requestBatch).toHaveBeenNthCalledWith(2, siteName, managedPath, [
      `/sitegroups/getById(12)/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=${SHAREPOINT_REST_PAGE_SIZE}`,
    ]);
    expect(result['12']).toHaveLength(SHAREPOINT_REST_PAGE_SIZE + 1);
    expect(result['12']?.at(-1)?.Id).toBe(SHAREPOINT_REST_PAGE_SIZE + 1);
  });

  it('stops paging a group once a short page is returned while continuing others', async () => {
    const fullPage = Array.from({ length: SHAREPOINT_REST_PAGE_SIZE }, (_, index) =>
      createMembership(index + 1),
    );
    const shortPage = [createMembership(1), createMembership(2)];
    requestBatch
      .mockResolvedValueOnce([{ value: fullPage }, { value: shortPage }])
      .mockResolvedValueOnce([{ value: [createMembership(SHAREPOINT_REST_PAGE_SIZE + 1)] }]);

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12', '34']);

    expect(requestBatch).toHaveBeenCalledTimes(2);
    expect(requestBatch).toHaveBeenNthCalledWith(2, siteName, managedPath, [
      `/sitegroups/getById(12)/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=${SHAREPOINT_REST_PAGE_SIZE}`,
    ]);
    expect(result['12']).toHaveLength(SHAREPOINT_REST_PAGE_SIZE + 1);
    expect(result['34']).toEqual(shortPage);
  });

  it('returns empty memberships when no group ids are provided', async () => {
    const result = await service.getSiteGroupsMemberships(siteName, managedPath, []);

    expect(requestBatch).not.toHaveBeenCalled();
    expect(result).toEqual({});
  });
});
