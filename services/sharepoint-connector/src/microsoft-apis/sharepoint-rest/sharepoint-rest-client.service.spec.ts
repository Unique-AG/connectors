import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { createSmeared } from '../../utils/smeared';
import {
  PrincipalType,
  SHAREPOINT_REST_PAGE_SIZE,
  SharepointRestClientService,
  type SiteGroupMembership,
} from './sharepoint-rest-client.service';
import { SharepointRestError, SharepointRestHttpService } from './sharepoint-rest-http.service';

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
  let requestSingle: Mock;
  let requestDownload: Mock;

  const siteName = createSmeared('Contoso');
  const managedPath = 'sites' as const;

  beforeEach(async () => {
    requestSingle = vi.fn();
    requestDownload = vi.fn();

    const { unit } = await TestBed.solitary(SharepointRestClientService)
      .mock(SharepointRestHttpService)
      .impl(() => ({ requestSingle, requestDownload }))
      .compile();
    service = unit;
  });

  it('fetches a single page when a group has fewer members than the page size', async () => {
    const members = [createMembership(1), createMembership(2)];
    requestSingle.mockResolvedValueOnce({ value: members });

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12']);

    expect(requestSingle).toHaveBeenCalledOnce();
    expect(requestSingle).toHaveBeenCalledWith(
      siteName,
      managedPath,
      `web/sitegroups/getById(12)/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=0`,
    );
    expect(result).toEqual({ membershipsByGroupId: { '12': members }, unreadableGroupIds: [] });
  });

  const membershipPage = (groupId: string, skip: number) =>
    `web/sitegroups/getById(${groupId})/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=${skip}`;

  const answerByPath = (pages: Record<string, SiteGroupMembership[]>) => {
    requestSingle.mockImplementation(async (_siteName, _managedPath, path: string) => ({
      value: pages[path] ?? [],
    }));
  };

  const requestedPaths = () => requestSingle.mock.calls.map(([, , path]) => path);

  it('pages until every group membership is fetched', async () => {
    const firstPage = Array.from({ length: SHAREPOINT_REST_PAGE_SIZE }, (_, index) =>
      createMembership(index + 1),
    );
    const secondPage = [createMembership(SHAREPOINT_REST_PAGE_SIZE + 1)];
    answerByPath({
      [membershipPage('12', 0)]: firstPage,
      [membershipPage('12', SHAREPOINT_REST_PAGE_SIZE)]: secondPage,
    });

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12']);

    expect(result).toEqual({
      membershipsByGroupId: { '12': [...firstPage, ...secondPage] },
      unreadableGroupIds: [],
    });
    expect(requestedPaths().sort()).toEqual(
      [membershipPage('12', 0), membershipPage('12', SHAREPOINT_REST_PAGE_SIZE)].sort(),
    );
  });

  it('stops paging a group once a short page is returned while continuing others', async () => {
    const fullPage = Array.from({ length: SHAREPOINT_REST_PAGE_SIZE }, (_, index) =>
      createMembership(index + 1),
    );
    const shortPage = [createMembership(1), createMembership(2)];
    const lastPage = [createMembership(SHAREPOINT_REST_PAGE_SIZE + 1)];
    answerByPath({
      [membershipPage('12', 0)]: fullPage,
      [membershipPage('34', 0)]: shortPage,
      [membershipPage('12', SHAREPOINT_REST_PAGE_SIZE)]: lastPage,
    });

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12', '34']);

    expect(result).toEqual({
      membershipsByGroupId: { '12': [...fullPage, ...lastPage], '34': shortPage },
      unreadableGroupIds: [],
    });
    expect(requestedPaths().sort()).toEqual(
      [
        membershipPage('12', 0),
        membershipPage('34', 0),
        membershipPage('12', SHAREPOINT_REST_PAGE_SIZE),
      ].sort(),
    );
  });

  const forbidden = () =>
    new SharepointRestError('Forbidden', 403, '-2147024891, System.UnauthorizedAccessException');

  it('reports site groups whose members SharePoint refuses to list and keeps the others', async () => {
    const readableMembers = [createMembership(1)];
    requestSingle.mockImplementation(async (_siteName, _managedPath, path: string) => {
      if (path === membershipPage('34', 0)) {
        return { value: readableMembers };
      }
      throw forbidden();
    });

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, [
      '12',
      '34',
      '56',
    ]);

    expect(result).toEqual({
      membershipsByGroupId: { '34': readableMembers },
      unreadableGroupIds: ['12', '56'],
    });
  });

  it('drops the members of a site group that becomes unreadable on a later page', async () => {
    const firstPage = Array.from({ length: SHAREPOINT_REST_PAGE_SIZE }, (_, index) =>
      createMembership(index + 1),
    );
    requestSingle.mockImplementation(async (_siteName, _managedPath, path: string) => {
      if (path === membershipPage('12', 0)) {
        return { value: firstPage };
      }
      throw forbidden();
    });

    const result = await service.getSiteGroupsMemberships(siteName, managedPath, ['12']);

    expect(result).toEqual({ membershipsByGroupId: {}, unreadableGroupIds: ['12'] });
  });

  it('rethrows other failures of a site group request', async () => {
    const serverError = new SharepointRestError('Server error', 500, undefined);
    requestSingle.mockRejectedValue(serverError);

    await expect(service.getSiteGroupsMemberships(siteName, managedPath, ['12'])).rejects.toBe(
      serverError,
    );
  });

  it('returns empty memberships when no group ids are provided', async () => {
    const result = await service.getSiteGroupsMemberships(siteName, managedPath, []);

    expect(requestSingle).not.toHaveBeenCalled();
    expect(result).toEqual({ membershipsByGroupId: {}, unreadableGroupIds: [] });
  });

  it('loads attachment names and sizes from the per-item attachment folders', async () => {
    const folders = [{ Name: '4', Files: [] }];
    requestSingle.mockResolvedValueOnce({ value: folders });

    const result = await service.getListItemAttachments(siteName, managedPath, 'list-id');

    expect(result).toBe(folders);
    expect(requestSingle).toHaveBeenCalledWith(
      siteName,
      managedPath,
      "web/lists(guid'list-id')/RootFolder/Folders('Attachments')/Folders?$select=Name,Files/Name,Files/Length,Files/ServerRelativeUrl&$expand=Files",
      { headersTimeout: 120_000, retryStatusCodes: [429, 502, 503, 504] },
    );
  });

  it('doubles single quotes in an attachment file name', async () => {
    requestDownload.mockResolvedValueOnce(undefined);

    await service.downloadListItemAttachment(
      siteName,
      managedPath,
      'list-id',
      '7',
      "o'brien file.pdf",
    );

    expect(requestDownload.mock.calls[0]?.[2]).toBe(
      "web/lists(guid'list-id')/items(7)/AttachmentFiles('o''brien%20file.pdf')/$value",
    );
  });
});
