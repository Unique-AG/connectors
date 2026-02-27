import { Injectable } from '@nestjs/common';
import { UniqueAuthMode, type UniqueConfig } from '../../config';
import { ServiceRegistry } from '../../tenant/service-registry';
import { ClusterLocalAuthStrategy } from './strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from './strategies/zitadel-auth.strategy';
import type { UniqueAuth } from './unique-auth.abstract';

@Injectable()
export class UniqueAuthFactory {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public create(uniqueConfig: UniqueConfig): UniqueAuth {
    const logger = this.serviceRegistry.getServiceLogger(UniqueAuthFactory);
    switch (uniqueConfig.serviceAuthMode) {
      case UniqueAuthMode.CLUSTER_LOCAL: {
        logger.info('Using cluster_local authentication for Unique services');
        return new ClusterLocalAuthStrategy(uniqueConfig);
      }
      case UniqueAuthMode.EXTERNAL: {
        logger.info('Using Zitadel external authentication for Unique services');
        const strategyLogger = this.serviceRegistry.getServiceLogger(ZitadelAuthStrategy);
        return new ZitadelAuthStrategy(uniqueConfig, strategyLogger);
      }
      default: {
        throw new Error(`Unsupported Unique auth mode`);
      }
    }
  }
}
