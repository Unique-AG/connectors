import { Logger } from '@nestjs/common';
import { Agent, interceptors } from 'undici';
import { UniqueAuth } from '../auth/unique-auth';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { UniqueHttpClient } from '../clients/unique-http.client';
import { UniqueApiFeatureModuleOptions } from '../config/unique-api-feature-module-options';
import { ContentService } from '../content/content.service';
import { FilesService } from '../files/files.service';
import { GroupsService } from '../groups/groups.service';
import { FileIngestionService } from '../ingestion/ingestion.service';
import { ScopesService } from '../scopes/scopes.service';
import type { UniqueApiClient } from '../types';
import { UsersService } from '../users/users.service';
import { BottleneckFactory } from './bottleneck.factory';
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

    const scopeManagementGraphQlClient = new UniqueGraphqlClient(
      auth,
      this.metrics,
      this.logger,
      dispatcher,
      this.bottleneckFactory,
      {
        target: 'scopeManagement',
        baseUrl: config.scopeManagement.baseUrl,
        rateLimitPerMinute: config.scopeManagement.rateLimitPerMinute,
        clientName: config.metadata.clientName,
      },
    );

    const ingestionGraphQlClient = new UniqueGraphqlClient(
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

    const ingestionHttpClient = new UniqueHttpClient(
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
      ingestionGraphQlClient,
      this.logger,
    );

    const files = new FilesService(ingestionGraphQlClient, this.logger);

    const users = new UsersService(scopeManagementGraphQlClient, this.logger);

    const groups = new GroupsService(scopeManagementGraphQlClient, this.logger);

    const ingestion = new FileIngestionService(
      ingestionGraphQlClient,
      ingestionHttpClient,
      config.ingestion.baseUrl,
    );

    const content = new ContentService(
      ingestionHttpClient,
      ingestionGraphQlClient,
      config.ingestion.baseUrl,
    );

    return {
      auth,
      scopes,
      files,
      users,
      groups,
      ingestion,
      content,
      close: async () => {
        await Promise.all([
          scopeManagementGraphQlClient.close(),
          ingestionGraphQlClient.close(),
          ingestionHttpClient.close(),
        ]);
        if (isOwnedDispatcher) {
          await dispatcher.close();
        }
      },
    };
  }
}
