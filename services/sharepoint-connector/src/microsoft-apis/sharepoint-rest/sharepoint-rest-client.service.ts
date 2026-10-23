import assert from 'node:assert';
import type { Readable } from 'node:stream';
import { Injectable, Logger } from '@nestjs/common';
import pLimit from 'p-limit';
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
import { SharepointRestError, SharepointRestHttpService } from './sharepoint-rest-http.service';

export const SHAREPOINT_REST_PAGE_SIZE = 100 as const;
const SITE_GROUP_MEMBERSHIP_CONCURRENCY = 4;
// SharePoint walks the whole list before it sends the first byte, about 6 ms per item, which is
// close to 30 s at the 5000-item list view threshold.
const LIST_ATTACHMENTS_HEADERS_TIMEOUT_MS = 120_000;
// SharePoint answers a list above the list view threshold with an immediate 500, so 500 is not
// retried: four retries only delay the site abort by about 45 s and hide the error code.
const LIST_ATTACHMENTS_RETRY_STATUS_CODES = [429, 502, 503, 504];

export class SiteGroupMembersNotReadableError extends Error {
  public constructor(siteName: Smeared, groupIds: string[]) {
    super(
      `Cannot read the members of site groups ${groupIds.join(', ')} on site "${siteName}": ` +
        `SharePoint answered 403. The groups' "Who can view the membership of the group?" ` +
        `setting is most likely not "Everyone". Set it to "Everyone", or make the app a member ` +
        `or owner of these groups.`,
    );
    this.name = 'SiteGroupMembersNotReadableError';
  }
}

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
    const limit = pLimit(SITE_GROUP_MEMBERSHIP_CONCURRENCY);
    let skip = 0;
    let remainingGroupIds = [...siteGroupIds];
    const membershipsByGroupId: Record<string, SiteGroupMembership[]> = fromEntries(
      siteGroupIds.map((id): [string, SiteGroupMembership[]] => [id, []]),
    );

    while (remainingGroupIds.length > 0) {
      const groupsOnPage = remainingGroupIds.length;
      const pages = await Promise.all(
        remainingGroupIds.map((id) =>
          limit(() => this.fetchSiteGroupMembersPage(siteName, managedPath, id, skip)),
        ),
      );

      const unreadableGroupIds = pipe(
        zip(remainingGroupIds, pages),
        filter(([, page]) => page === undefined),
        map(([groupId]) => groupId),
      );
      if (unreadableGroupIds.length > 0) {
        throw new SiteGroupMembersNotReadableError(siteName, unreadableGroupIds);
      }

      remainingGroupIds = pipe(
        zip(remainingGroupIds, pages),
        map(([groupId, page]) => {
          const pageMembers = page ?? [];
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

  // Gives undefined when SharePoint refuses to list the group's members.
  private async fetchSiteGroupMembersPage(
    siteName: Smeared,
    managedPath: ManagedPath,
    groupId: string,
    skip: number,
  ): Promise<SiteGroupMembership[] | undefined> {
    try {
      const response = await this.sharepointRestHttpService.requestSingle<{
        value: SiteGroupMembership[];
      }>(
        siteName,
        managedPath,
        `web/sitegroups/getById(${groupId})/users?$top=${SHAREPOINT_REST_PAGE_SIZE}&$skip=${skip}`,
      );
      return response.value;
    } catch (error) {
      if (error instanceof SharepointRestError && error.statusCode === 403) {
        return undefined;
      }
      throw error;
    }
  }

  // SharePoint keeps one folder per item, named after the item id, under the list's Attachments
  // folder. Unlike the items endpoint, this one returns each file's size. It returns every folder
  // in one response: `$top` truncates it without a next link. On a list above the list view
  // threshold SharePoint rejects it with SPQueryThrottledException, however few items have
  // attachments.
  public async getListItemAttachments(
    siteName: Smeared,
    managedPath: ManagedPath,
    listId: string,
  ): Promise<RestAttachmentFolder[]> {
    const response = await this.sharepointRestHttpService.requestSingle<{
      value: RestAttachmentFolder[];
    }>(
      siteName,
      managedPath,
      `web/lists(guid'${listId}')/RootFolder/Folders('Attachments')/Folders?$select=Name,Files/Name,Files/Length,Files/ServerRelativeUrl&$expand=Files`,
      {
        headersTimeout: LIST_ATTACHMENTS_HEADERS_TIMEOUT_MS,
        retryStatusCodes: LIST_ATTACHMENTS_RETRY_STATUS_CODES,
      },
    );
    return response.value;
  }

  public async getListReadSecurity(
    siteName: Smeared,
    managedPath: ManagedPath,
    listId: string,
  ): Promise<number> {
    const response = await this.sharepointRestHttpService.requestSingle<{ ReadSecurity: number }>(
      siteName,
      managedPath,
      `web/lists(guid'${listId}')?$select=ReadSecurity`,
    );
    return response.ReadSecurity;
  }

  public async downloadListItemAttachment(
    siteName: Smeared,
    managedPath: ManagedPath,
    listId: string,
    itemId: string,
    fileName: string,
  ): Promise<Readable> {
    // SharePoint OData string literals escape a single quote by doubling it.
    const encodedName = encodeURIComponent(fileName.replaceAll("'", "''"));
    const path = `web/lists(guid'${listId}')/items(${itemId})/AttachmentFiles('${encodedName}')/$value`;
    return await this.sharepointRestHttpService.requestDownload(siteName, managedPath, path);
  }
}

interface RestAttachmentFile {
  Name: string;
  Length: string; // SharePoint serializes Int64 values as strings.
  ServerRelativeUrl: string;
}

interface RestAttachmentFolder {
  Name: string;
  Files: RestAttachmentFile[];
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
