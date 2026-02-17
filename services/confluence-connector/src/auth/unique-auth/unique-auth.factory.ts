import { Injectable, Logger } from '@nestjs/common';
import { UniqueAuthMode, type UniqueConfig } from '../../config';
import { ClusterLocalAuthStrategy } from './strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from './strategies/zitadel-auth.strategy';
import type { UniqueAuthAbstract } from './unique-auth.abstract';

@Injectable()
export class UniqueAuthFactory {
  private readonly logger = new Logger(UniqueAuthFactory.name);

  public create(uniqueConfig: UniqueConfig): UniqueAuthAbstract {
    switch (uniqueConfig.serviceAuthMode) {
      case UniqueAuthMode.CLUSTER_LOCAL: {
        this.logger.log('Using cluster_local authentication for Unique services');
        return new ClusterLocalAuthStrategy(uniqueConfig);
      }
      case UniqueAuthMode.EXTERNAL: {
        this.logger.log('Using Zitadel external authentication for Unique services');
        return new ZitadelAuthStrategy(uniqueConfig);
      }
      default: {
        throw new Error(`Unsupported Unique auth mode`);
      }
    }
  }
}
