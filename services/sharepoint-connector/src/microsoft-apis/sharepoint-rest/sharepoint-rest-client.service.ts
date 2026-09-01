import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import {
  filter,
  forEach,
  fromEntries,
  map,
  pipe,
  prop,
  sumBy,
  uniqueBy,
  values,
  zip,
} from 'remeda';
import type { ManagedPath } from '../../utils/paths.util';
import type { Smeared } from '../../utils/smeared';
import { SharepointRestHttpService } from './sharepoint-rest-http.service';

export const SHAREPOINT_REST_PAGE_SIZE = 100 as const;

@Injectable()
export class SharepointRestClientService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly sharepointRestHttpService: SharepointRestHttpService) {}

  public async getSiteGroupsMemberships(
    siteName: Smeared,
    managedPath: ManagedPath,
    siteGroupIds: string[],
  ): Promise<Record<string, SiteGroupMembership[]>> {
    const logPrefix = `[Site: ${siteName}]`;
    let skip = 0;
    let remainingGroupIds = [...siteGroupIds];
    const membershipsByGroupId: Record<string, SiteGroupMembership[]> = fromEntries(
      siteGroupIds.map((id): [string, SiteGroupMembership[]] => [id, []]),
    );

    while (remainingGroupIds.length > 0) {
      const groupsOnPage = remainingGroupIds.length;
      const responses = await this.sharepointRestHttpService.requestBatch<{
        value: SiteGroupMembership[];
      }>(
        siteName,
        managedPath,
        remainingGroupIds.map(
          (id) =>
            `/sitegroups/getById(${id})/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=${skip}`,
        ),
      );

      remainingGroupIds = pipe(
        zip(remainingGroupIds, responses),
        map(([groupId, response]) => {
          const pageMembers = response?.value ?? [];
          const existingMembers = membershipsByGroupId[groupId];
          assert(existingMembers, `No existing members found for group ${groupId}`);
          return {
            groupId,
            members: uniqueBy([...existingMembers, ...pageMembers], prop('Id')),
            shouldContinue: pageMembers.length === SHAREPOINT_REST_PAGE_SIZE,
          };
        }),
        forEach(({ groupId, members }) => {
          membershipsByGroupId[groupId] = members;
        }),
        filter(prop('shouldContinue')),
        map(prop('groupId')),
      );

      this.logger.debug(
        `${logPrefix} Site group memberships page skip=${skip}: ${groupsOnPage} groups, ` +
          `${remainingGroupIds.length} continuing`,
      );
      skip += SHAREPOINT_REST_PAGE_SIZE;
    }

    if (siteGroupIds.length > 0) {
      const membershipCount = sumBy(values(membershipsByGroupId), (members) => members.length);
      this.logger.log(
        `${logPrefix} Fetched ${membershipCount} memberships across ${siteGroupIds.length} site ` +
          `groups in ${skip / SHAREPOINT_REST_PAGE_SIZE} page(s)`,
      );
    }

    return membershipsByGroupId;
  }
}

export interface SiteGroupMembership {
  Id: number;
  PrincipalType: PrincipalType;
  LoginName: string;
  Email: string;
  Title: string;
}

export const PrincipalType = {
  User: 1,
  DistributionList: 2,
  SecurityGroup: 4,
  SharePointGroup: 8,
} as const;

export type PrincipalType = (typeof PrincipalType)[keyof typeof PrincipalType];
