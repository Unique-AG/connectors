import { Injectable } from '@nestjs/common';
import { fromEntries, map, pipe, prop, zip } from 'remeda';
import { SharepointRestHttpService } from './sharepoint-rest-http.service';

@Injectable()
export class SharepointRestClientService {
  public constructor(private readonly sharepointRestHttpService: SharepointRestHttpService) {}

  public async getSiteGroupsMemberships(
    siteName: string,
    siteGroupIds: string[],
  ): Promise<Record<string, SiteGroupMembership[]>> {
    const responses = await this.sharepointRestHttpService.requestBatch<{
      value: SiteGroupMembership[];
    }>(
      siteName,
      siteGroupIds.map((id) => `/sitegroups/getById(${id})/users`),
    );

    return pipe(
      responses,
      map(prop('value')),
      (membershipsLists) => zip(siteGroupIds, membershipsLists),
      fromEntries(),
    );
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
