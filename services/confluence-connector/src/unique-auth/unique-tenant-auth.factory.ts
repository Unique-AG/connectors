import { Injectable, Logger } from '@nestjs/common';
import type { UniqueConfig } from '../config/unique.schema';
import { ClusterLocalAuthStrategy } from './strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from './strategies/zitadel-auth.strategy';
import type { UniqueServiceAuth } from './unique-service-auth';

@Injectable()
export class UniqueTenantAuthFactory {
  private readonly logger = new Logger(UniqueTenantAuthFactory.name);

  public create(uniqueConfig: UniqueConfig): UniqueServiceAuth {
    switch (uniqueConfig.serviceAuthMode) {
      case 'cluster_local': {
        this.logger.log('Using cluster_local authentication for Unique services');
        return new ClusterLocalAuthStrategy(uniqueConfig);
      }
      case 'external': {
        this.logger.log('Using Zitadel external authentication for Unique services');
        return new ZitadelAuthStrategy(uniqueConfig);
      }
      default: {
        const exhaustive: never = uniqueConfig;
        throw new Error(
          `Unsupported Unique service auth mode: ${(exhaustive as { serviceAuthMode: string }).serviceAuthMode}`,
        );
      }
    }
  }
}
