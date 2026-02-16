import {
  type DynamicModule,
  Inject,
  Logger,
  Module,
  type OnModuleDestroy,
  type Provider,
} from '@nestjs/common';
import { type Meter, metrics } from '@opentelemetry/api';
import type {
  UniqueApiClientConfig,
  UniqueApiClientFactory,
  UniqueApiClientRegistry,
  UniqueApiFeatureAsyncOptions,
  UniqueApiModuleAsyncOptions,
  UniqueApiModuleOptions,
} from '../types';
import { BottleneckFactory } from './bottleneck.factory';
import { createUniqueApiMetrics, type UniqueApiMetrics } from './observability';
import {
  getUniqueApiClientToken,
  UNIQUE_API_CLIENT_FACTORY,
  UNIQUE_API_CLIENT_REGISTRY,
  UNIQUE_API_METER,
  UNIQUE_API_METRICS,
  UNIQUE_API_MODULE_OPTIONS,
} from './tokens';
import { UniqueApiClientFactoryImpl } from './unique-api-client.factory';
import { UniqueApiClientRegistryImpl } from './unique-api-client.registry';

@Module({})
export class UniqueApiModule implements OnModuleDestroy {
  public constructor(
    @Inject(UNIQUE_API_CLIENT_REGISTRY)
    private readonly registry: UniqueApiClientRegistry,
  ) {}

  public async onModuleDestroy(): Promise<void> {
    await this.registry.clear();
  }

  public static forRoot(options: UniqueApiModuleOptions = {}): DynamicModule {
    return {
      module: UniqueApiModule,
      global: true,
      providers: [
        { provide: UNIQUE_API_MODULE_OPTIONS, useValue: options },
        ...UniqueApiModule.createCoreProviders(),
      ],
      exports: [UNIQUE_API_CLIENT_FACTORY, UNIQUE_API_CLIENT_REGISTRY, UNIQUE_API_METRICS],
    };
  }

  public static forRootAsync(options: UniqueApiModuleAsyncOptions): DynamicModule {
    return {
      module: UniqueApiModule,
      global: true,
      imports: options.imports,
      providers: [
        {
          provide: UNIQUE_API_MODULE_OPTIONS,
          useFactory: options.useFactory,
          inject: options.inject,
        },
        ...UniqueApiModule.createCoreProviders(),
      ],
      exports: [UNIQUE_API_CLIENT_FACTORY, UNIQUE_API_CLIENT_REGISTRY, UNIQUE_API_METRICS],
    };
  }

  public static forFeature(name: string, config: UniqueApiClientConfig): DynamicModule {
    const token = getUniqueApiClientToken(name);
    return {
      module: UniqueApiModule,
      providers: [
        {
          provide: token,
          useFactory: (factory: UniqueApiClientFactory, registry: UniqueApiClientRegistry) => {
            const client = factory.create(config);
            registry.set(name, client);
            return client;
          },
          inject: [UNIQUE_API_CLIENT_FACTORY, UNIQUE_API_CLIENT_REGISTRY],
        },
      ],
      exports: [token],
    };
  }

  public static forFeatureAsync(
    name: string,
    options: UniqueApiFeatureAsyncOptions,
  ): DynamicModule {
    const token = getUniqueApiClientToken(name);
    return {
      module: UniqueApiModule,
      imports: options.imports,
      providers: [
        {
          provide: token,
          useFactory: async (
            factory: UniqueApiClientFactory,
            registry: UniqueApiClientRegistry,
            ...args: unknown[]
          ) => {
            const config = await options.useFactory(...(args as never[]));
            const client = factory.create(config);
            registry.set(name, client);
            return client;
          },
          inject: [
            UNIQUE_API_CLIENT_FACTORY,
            UNIQUE_API_CLIENT_REGISTRY,
            ...(options.inject ?? []),
          ],
        },
      ],
      exports: [token],
    };
  }

  private static createCoreProviders(): Provider[] {
    return [
      BottleneckFactory,
      {
        provide: UNIQUE_API_METER,
        useFactory: (options: UniqueApiModuleOptions) => {
          const meterName = options.observability?.metricPrefix ?? 'unique_api';
          return metrics.getMeter(meterName);
        },
        inject: [UNIQUE_API_MODULE_OPTIONS],
      },
      {
        provide: UNIQUE_API_METRICS,
        useFactory: (meter: Meter, options: UniqueApiModuleOptions) => {
          const prefix = options.observability?.metricPrefix ?? 'unique_api';
          return createUniqueApiMetrics(meter, prefix);
        },
        inject: [UNIQUE_API_METER, UNIQUE_API_MODULE_OPTIONS],
      },
      {
        provide: UNIQUE_API_CLIENT_FACTORY,
        useFactory: (
          metricsInstance: UniqueApiMetrics,
          options: UniqueApiModuleOptions,
          bottleneckFactory: BottleneckFactory,
        ) => {
          const loggerContext = options.observability?.loggerContext ?? 'UniqueApi';
          const logger = new Logger(loggerContext);
          return new UniqueApiClientFactoryImpl({
            logger,
            metrics: metricsInstance,
            bottleneckFactory,
          });
        },
        inject: [UNIQUE_API_METRICS, UNIQUE_API_MODULE_OPTIONS, BottleneckFactory],
      },
      {
        provide: UNIQUE_API_CLIENT_REGISTRY,
        useFactory: (factory: UniqueApiClientFactory) => new UniqueApiClientRegistryImpl(factory),
        inject: [UNIQUE_API_CLIENT_FACTORY],
      },
    ];
  }
}
