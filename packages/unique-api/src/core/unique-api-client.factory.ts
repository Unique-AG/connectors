import { Agent, interceptors } from 'undici';
import { UniqueAuth } from '../auth/unique-auth';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { FilesService } from '../files/files.service';
import { GroupsService } from '../groups/groups.service';
import { FileIngestionService } from '../ingestion/ingestion.service';
import { ScopesService } from '../scopes/scopes.service';
import { UsersService } from '../users/users.service';
import type { UniqueApiMetrics } from './observability';
import type { UniqueApiClient, UniqueApiClientConfig, UniqueApiClientFactory } from './types';

interface UniqueApiClientFactoryLogger {
  log(message: string): void;
  error(obj: object): void;
  warn(obj: object): void;
  debug(message: string): void;
}

interface UniqueApiClientFactoryDeps {
  logger: UniqueApiClientFactoryLogger;
  metrics: UniqueApiMetrics;
}

export class UniqueApiClientFactoryImpl implements UniqueApiClientFactory {
  private readonly logger: UniqueApiClientFactoryLogger;
  private readonly metrics: UniqueApiMetrics;

  public constructor(deps: UniqueApiClientFactoryDeps) {
    this.logger = deps.logger;
    this.metrics = deps.metrics;
  }

  public create(config: UniqueApiClientConfig): UniqueApiClient {
    const clientName = config.metadata?.clientName;
    const isOwnedDispatcher = !config.dispatcher;
    const dispatcher =
      config.dispatcher ?? new Agent().compose([interceptors.retry(), interceptors.redirect()]);

    const auth = new UniqueAuth({
      config: config.auth,
      metrics: this.metrics,
      logger: this.logger,
      dispatcher,
    });

    const scopeManagementClient = new UniqueGraphqlClient({
      target: 'scopeManagement',
      baseUrl: config.endpoints.scopeManagementBaseUrl,
      auth,
      metrics: this.metrics,
      logger: this.logger,
      rateLimitPerMinute: config.rateLimitPerMinute,
      dispatcher,
      clientName,
    });

    const ingestionClient = new UniqueGraphqlClient({
      target: 'ingestion',
      baseUrl: config.endpoints.ingestionBaseUrl,
      auth,
      metrics: this.metrics,
      logger: this.logger,
      rateLimitPerMinute: config.rateLimitPerMinute,
      dispatcher,
      clientName,
    });

    const ingestionHttpClient = new IngestionHttpClient({
      baseUrl: config.endpoints.ingestionBaseUrl,
      auth,
      metrics: this.metrics,
      logger: this.logger,
      rateLimitPerMinute: config.rateLimitPerMinute,
      dispatcher,
      clientName,
    });

    const scopes = new ScopesService({
      scopeManagementClient,
      logger: this.logger,
    });

    const files = new FilesService({
      ingestionClient,
      logger: this.logger,
    });

    const users = new UsersService({
      scopeManagementClient,
      logger: this.logger,
    });

    const groups = new GroupsService({
      scopeManagementClient,
      logger: this.logger,
    });

    const ingestion = new FileIngestionService({
      ingestionClient,
      ingestionHttpClient,
      ingestionBaseUrl: config.endpoints.ingestionBaseUrl,
    });

    return {
      auth: {
        getToken: () => auth.getToken(),
      },
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
