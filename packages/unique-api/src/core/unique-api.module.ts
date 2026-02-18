import {
  ConfigurableModuleAsyncOptions,
  type DynamicModule,
  Inject,
  Logger,
  Module,
  type OnModuleDestroy,
  type Provider,
} from '@nestjs/common';
import { Meter, metrics } from '@opentelemetry/api';
import {
  UniqueApiFeatureModuleInputOptions,
  UniqueApiFeatureModuleOptions,
  uniqueApiFeatureModuleOptionsHost,
} from '../config/unique-api-feature-module-options';
import {
  UniqueApiRootModuleInputOptions,
  UniqueApiRootModuleOptions,
  uniqueApiRootModuleHost,
} from '../config/unique-api-root-module-options';
import type { UniqueApiClientFactory, UniqueApiClientRegistry } from '../types';
import { BottleneckFactory } from './bottleneck.factory';
import { createUniqueApiMetrics, UniqueApiMetrics } from './observability';
import {
  getUniqueApiClientToken,
  UNIQUE_API_CLIENT_FACTORY,
  UNIQUE_API_CLIENT_REGISTRY,
  UNIQUE_API_METER,
  UNIQUE_API_METRICS,
} from './tokens';
import { UniqueApiClientFactoryImpl } from './unique-api-client.factory';
import { UniqueApiClientRegistryImpl } from './unique-api-client.registry';

@Module({})
class UniqueApiRoot
  extends uniqueApiRootModuleHost.ConfigurableModuleClass
  implements OnModuleDestroy
{
  public constructor(
    @Inject(UNIQUE_API_CLIENT_REGISTRY)
    private readonly registry: UniqueApiClientRegistry,
  ) {
    super();
  }

  public async onModuleDestroy(): Promise<void> {
    await this.registry.clear();
  }
}

@Module({})
class UniqueApiFeature extends uniqueApiFeatureModuleOptionsHost.ConfigurableModuleClass {}

export const UniqueApiModule = {
  forRoot: (options: UniqueApiRootModuleInputOptions): DynamicModule => {
    const dynamicModule = UniqueApiRoot.forRoot(options);
    return {
      ...dynamicModule,
      global: true,
      providers: [...(dynamicModule?.providers ?? []), ...createCoreProviders()],
      exports: [...(dynamicModule?.exports ?? []), ...createCoreProviders()],
    };
  },

  forRootAsync: (
    options: ConfigurableModuleAsyncOptions<UniqueApiRootModuleInputOptions>,
  ): DynamicModule => {
    const dynamicModule = UniqueApiRoot.forRootAsync(options);

    return {
      ...dynamicModule,
      global: true,
      providers: [...(dynamicModule.providers ?? []), ...createCoreProviders()],
      exports: [
        ...(dynamicModule.exports ?? []),
        UNIQUE_API_CLIENT_FACTORY,
        UNIQUE_API_CLIENT_REGISTRY,
        UNIQUE_API_METRICS,
      ],
    };
  },

  forFeature: (name: string, options: UniqueApiFeatureModuleInputOptions): DynamicModule => {
    const token = getUniqueApiClientToken(name);
    const dynamicModule = UniqueApiFeature.forFeature(options);

    return {
      ...dynamicModule,
      providers: [
        ...(dynamicModule?.providers ?? []),
        {
          provide: token,
          useFactory: (
            factory: UniqueApiClientFactory,
            registry: UniqueApiClientRegistry,
            config: UniqueApiFeatureModuleOptions,
          ) => {
            const client = factory.create(config);
            try {
              registry.set(name, client);
              return client;
            } catch (error) {
              client.close?.();
              throw error;
            }
          },
          inject: [
            UNIQUE_API_CLIENT_FACTORY,
            UNIQUE_API_CLIENT_REGISTRY,
            uniqueApiFeatureModuleOptionsHost.MODULE_OPTIONS_TOKEN,
          ],
        },
      ],
      exports: [...(dynamicModule?.exports ?? []), token],
    };
  },

  forFeatureAsync: (
    name: string,
    options: ConfigurableModuleAsyncOptions<UniqueApiFeatureModuleInputOptions>,
  ): DynamicModule => {
    const token = getUniqueApiClientToken(name);
    const dynamicModule = UniqueApiFeature.forFeatureAsync(options);

    return {
      ...dynamicModule,
      providers: [
        ...(dynamicModule?.providers ?? []),
        {
          provide: token,
          useFactory: (
            factory: UniqueApiClientFactory,
            registry: UniqueApiClientRegistry,
            config: UniqueApiFeatureModuleOptions,
          ) => {
            const client = factory.create(config);
            try {
              registry.set(name, client);
              return client;
            } catch (error) {
              client.close?.();
              throw error;
            }
          },
          inject: [
            UNIQUE_API_CLIENT_FACTORY,
            UNIQUE_API_CLIENT_REGISTRY,
            uniqueApiFeatureModuleOptionsHost.MODULE_OPTIONS_TOKEN,
          ],
        },
      ],
      exports: [...(dynamicModule?.exports ?? []), token],
    };
  },
};

const createCoreProviders = (): Provider[] => {
  return [
    BottleneckFactory,
    {
      provide: UNIQUE_API_METER,
      useFactory: (options: UniqueApiRootModuleOptions) => {
        return metrics.getMeter(options.observability.metricPrefix);
      },
      inject: [uniqueApiRootModuleHost.MODULE_OPTIONS_TOKEN],
    },
    {
      provide: UNIQUE_API_METRICS,
      useFactory: (meter: Meter, options: UniqueApiRootModuleOptions) => {
        return createUniqueApiMetrics(meter, options.observability.metricPrefix);
      },
      inject: [UNIQUE_API_METER, uniqueApiRootModuleHost.MODULE_OPTIONS_TOKEN],
    },
    {
      provide: UNIQUE_API_CLIENT_FACTORY,
      useFactory: (
        metricsInstance: UniqueApiMetrics,
        options: UniqueApiRootModuleOptions,
        bottleneckFactory: BottleneckFactory,
      ) => {
        const loggerContext = options.observability?.loggerContext ?? 'UniqueApi';
        const logger = new Logger(loggerContext);

        return new UniqueApiClientFactoryImpl(logger, metricsInstance, bottleneckFactory);
      },
      inject: [UNIQUE_API_METRICS, uniqueApiRootModuleHost.MODULE_OPTIONS_TOKEN, BottleneckFactory],
    },
    {
      provide: UNIQUE_API_CLIENT_REGISTRY,
      useFactory: (factory: UniqueApiClientFactory) => new UniqueApiClientRegistryImpl(factory),
      inject: [UNIQUE_API_CLIENT_FACTORY],
    },
  ];
};
