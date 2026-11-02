import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import {
  PrincipalType,
  SharepointRestClientService,
} from '../microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { createSmeared } from '../utils/smeared';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import type { GroupMembership } from './types';

describe('FetchGroupsWithMembershipsQuery', () => {
  let query: FetchGroupsWithMembershipsQuery;
  let getSiteGroupsMemberships: Mock;

  const siteId = createSmeared('site-id');
  const readableGroup: GroupMembership = { type: 'siteGroup', id: 'Contoso|3', name: 'Members' };
  const unreadableGroup: GroupMembership = { type: 'siteGroup', id: 'Contoso|7', name: 'Hidden' };

  beforeEach(async () => {
    getSiteGroupsMemberships = vi.fn().mockResolvedValue({
      membershipsByGroupId: {
        '3': [
          {
            Id: 11,
            PrincipalType: PrincipalType.User,
            LoginName: 'i:0#.f|membership|alice@example.com',
            Email: 'alice@example.com',
            Title: 'Alice',
          },
        ],
      },
      unreadableGroupIds: ['7'],
    });

    const { unit } = await TestBed.solitary(FetchGroupsWithMembershipsQuery)
      .mock(SharepointRestClientService)
      .impl(() => ({ getSiteGroupsMemberships }))
      .compile();
    query = unit;
  });

  // biome-ignore lint/suspicious/noExplicitAny: Access private logger
  const getLogger = () => (query as any).logger;

  it('syncs a site group whose members SharePoint refuses to list without members', async () => {
    const result = await query.run(siteId, 'sites', [readableGroup, unreadableGroup]);

    expect(result).toEqual({
      'siteGroup:Contoso|3': {
        id: 'siteGroup:Contoso|3',
        displayName: 'Members',
        members: ['alice@example.com'],
      },
      'siteGroup:Contoso|7': { id: 'siteGroup:Contoso|7', displayName: 'Hidden', members: [] },
    });
  });

  it('warns about the site groups whose members SharePoint refuses to list', async () => {
    const warnSpy = vi.spyOn(getLogger(), 'warn');

    await query.run(siteId, 'sites', [readableGroup, unreadableGroup]);

    expect(warnSpy).toHaveBeenCalledOnce();
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining(
        `[Site: ${siteId}] Cannot read the members of site groups 7: SharePoint answered 403.`,
      ),
    );
  });

  it('does not warn when every site group is readable', async () => {
    getSiteGroupsMemberships.mockResolvedValue({
      membershipsByGroupId: {},
      unreadableGroupIds: [],
    });
    const warnSpy = vi.spyOn(getLogger(), 'warn');

    await query.run(siteId, 'sites', [readableGroup]);

    expect(warnSpy).not.toHaveBeenCalled();
  });
});
