import { Logger } from '@nestjs/common';
import { Agent, interceptors } from 'undici';
import { UniqueAuth } from '../auth/unique-auth';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { FilesService } from '../files/files.service';
import { GroupsService } from '../groups/groups.service';
import { FileIngestionService } from '../ingestion/ingestion.service';
import { ScopesService } from '../scopes/scopes.service';
import type { UniqueApiClient } from '../types';
import { UsersService } from '../users/users.service';
import { BottleneckFactory } from './bottleneck.factory';
import { UniqueApiFeatureModuleOptions } from './config/unique-api-feature-module-options';
import type { UniqueApiMetrics } from './observability';

export interface UniqueApiClientFactory {
  create(config: UniqueApiFeatureModuleOptions): UniqueApiClient;
}

export class UniqueApiClientFactoryImpl implements UniqueApiClientFactory {
  public constructor(
    private readonly logger: Logger,
    private readonly metrics: UniqueApiMetrics,
    private readonly bottleneckFactory: BottleneckFactory,
  ) {}

  public create(config: UniqueApiFeatureModuleOptions): UniqueApiClient {
    const isOwnedDispatcher = !config.dispatcher;
    const dispatcher =
      config.dispatcher ?? new Agent().compose([interceptors.retry(), interceptors.redirect()]);

    const auth = new UniqueAuth(config.auth, this.metrics, this.logger, dispatcher);

    const scopeManagementClient = new UniqueGraphqlClient(
      auth,
      this.metrics,
      this.logger,
      dispatcher,
      this.bottleneckFactory,
      {
        target: 'scopeManagement',
        baseUrl: config.scopeManagment.baseUrl,
        rateLimitPerMinute: config.scopeManagment.rateLimitPerMinute,
        clientName: config.metadata.clientName,
      },
    );

    const ingestionClient = new UniqueGraphqlClient(
      auth,
      this.metrics,
      this.logger,
      dispatcher,
      this.bottleneckFactory,
      {
        target: 'ingestion',
        baseUrl: config.ingestion.baseUrl,
        rateLimitPerMinute: config.ingestion.rateLimitPerMinute,
        clientName: config.metadata.clientName,
      },
    );

    const ingestionHttpClient = new IngestionHttpClient(
      auth,
      this.metrics,
      this.logger,
      dispatcher,
      this.bottleneckFactory,
      {
        baseUrl: config.ingestion.baseUrl,
        rateLimitPerMinute: config.ingestion.rateLimitPerMinute,
        clientName: config.metadata.clientName,
      },
    );

    const scopes = new ScopesService(
      // Scope management was moved to ingestion.
      ingestionClient,
      this.logger,
      {
        defaultBatchSize: config.scopeManagment.batchSize,
      },
    );

    const files = new FilesService(ingestionClient, this.logger);

    const users = new UsersService(scopeManagementClient, this.logger, {
      defaultBatchSize: config.users.batchSize,
    });

    const groups = new GroupsService(scopeManagementClient, this.logger, {
      defaultBatchSize: config.users.batchSize,
    });

    const ingestion = new FileIngestionService(
      ingestionClient,
      ingestionHttpClient,
      config.ingestion.baseUrl,
    );

    return {
      auth,
      scopes,
      files,
      users,
      groups,
      ingestion,
      close: async () => {
        await Promise.all([
          scopeManagementClient.close(),
          ingestionClient.close(),
          ingestionHttpClient.close(),
        ]);
        if (isOwnedDispatcher) {
          await dispatcher.close();
        }
      },
    };
  }
}
