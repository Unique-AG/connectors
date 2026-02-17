import { Injectable, Logger } from '@nestjs/common';
import type { UniqueConfig } from '../../config';
import { ClusterLocalAuthStrategy } from './strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from './strategies/zitadel-auth.strategy';
import type { UniqueAuth } from './unique-auth';

@Injectable()
export class UniqueAuthFactory {
  private readonly logger = new Logger(UniqueAuthFactory.name);

  public create(uniqueConfig: UniqueConfig): UniqueAuth {
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
        throw new Error(`Unsupported Unique auth mode`);
      }
    }
  }
}
