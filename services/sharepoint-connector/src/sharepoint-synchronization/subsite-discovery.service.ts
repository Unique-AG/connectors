import assert from 'node:assert';
import type { Site } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { extractSiteNameFromWebUrl, normalizeSlashes } from '../utils/paths.util';
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

  public async discoverAllSubsites(
    rootSiteId: Smeared,
    rootSiteName: Smeared,
  ): Promise<DiscoveredSubsite[]> {
    return this.discoverRecursively(rootSiteId, rootSiteName);
  }

  private async discoverRecursively(
    siteId: Smeared,
    rootSiteName: Smeared,
  ): Promise<DiscoveredSubsite[]> {
    const subsites: Site[] = await this.graphApiService.getSubsites(siteId);
    const results: DiscoveredSubsite[] = [];

    for (const site of subsites) {
      assert.ok(site.id, 'Subsite missing id');
      assert.ok(site.webUrl, 'Subsite missing webUrl');

      const subsiteId = createSmeared(site.id);
      const subsiteName = createSmeared(extractSiteNameFromWebUrl(site.webUrl));
      const relativePath = rootSiteName.transform((rootName) =>
        normalizeSlashes(subsiteName.value.substring(rootName.length)),
      );

      results.push({ siteId: subsiteId, name: subsiteName, relativePath });

      this.logger.debug(`Discovered subsite "${subsiteName}" at path "${smearPath(relativePath)}"`);

      const nested = await this.discoverRecursively(subsiteId, rootSiteName);
      results.push(...nested);
    }

    return results;
  }
}
