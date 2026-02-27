import assert from 'node:assert';
import type { Site } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { createSmeared, Smeared, smearPath } from '../utils/smeared';

export interface DiscoveredSubsite {
  siteId: Smeared;
  name: Smeared;
  relativePath: Smeared;
}

@Injectable()
export class SubsiteDiscoveryService {
  private readonly logger = new Logger(SubsiteDiscoveryService.name);

  public constructor(private readonly graphApiService: GraphApiService) {}

  public async discoverAllSubsites(rootSiteId: Smeared): Promise<DiscoveredSubsite[]> {
    return this.discoverRecursively(rootSiteId, []);
  }

  private async discoverRecursively(
    siteId: Smeared,
    parentSegments: Smeared[],
  ): Promise<DiscoveredSubsite[]> {
    const subsites: Site[] = await this.graphApiService.getSubsites(siteId);
    const results: DiscoveredSubsite[] = [];

    for (const site of subsites) {
      assert(site.id, 'Subsite missing id');
      assert(site.name, 'Subsite missing name');

      const subsiteName = createSmeared(site.name);
      const subsiteId = createSmeared(site.id);
      const segments = [...parentSegments, subsiteName];
      const relativePath = createSmeared(segments.map((segment) => segment.value).join('/'));

      results.push({ siteId: subsiteId, name: subsiteName, relativePath });

      this.logger.debug(`Discovered subsite "${subsiteName}" at path "${smearPath(relativePath)}"`);

      const nested = await this.discoverRecursively(subsiteId, segments);
      results.push(...nested);
    }

    return results;
  }
}
