import { Injectable } from '@nestjs/common';
import { filter, pipe, uniqueBy } from 'remeda';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { SharepointRestClientService } from '../microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { ItemPermission } from './types';

interface GroupWithMemberships {
  id: `${ItemPermission['type']}:${ItemPermission['id']}`;
  displayName: string;
  members: string[]; // list of emails of the members
}

@Injectable()
export class FetchGroupsWithMembershipsQuery {
  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly sharepointRestClientService: SharepointRestClientService,
  ) {}

  public async run(siteId: string, permissions: ItemPermission[]): Promise<GroupWithMemberships[]> {
    const entraGroupsPermissions = pipe(
      permissions,
      filter((permission) => ['groupMembers', 'groupOwners'].includes(permission.type)),
      uniqueBy((permission) => `${permission.type}:${permission.id}`),
    );

    const siteGroupsPermissions = pipe(
      permissions,
      filter((permission) => permission.type === 'siteGroup'),
      uniqueBy((permission) => `${permission.type}:${permission.id}`),
    );
  }
}
