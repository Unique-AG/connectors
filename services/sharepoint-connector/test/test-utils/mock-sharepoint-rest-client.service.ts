import { vi } from 'vitest';

export class MockSharepointRestClientService {
  public groupMemberships: Record<string, unknown[]> = {};

  public getSiteGroupsMemberships = vi
    .fn()
    .mockImplementation(
      async (_siteName: string, siteGroupIds: string[]): Promise<Record<string, unknown[]>> => {
        return Object.fromEntries(siteGroupIds.map((id) => [id, this.groupMemberships[id] ?? []]));
      },
    );
}
