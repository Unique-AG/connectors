/** biome-ignore-all lint/complexity/noThisInStatic: Fork of KurtzL/nestjs-temporal */
import { DynamicModule, Module } from '@nestjs/common';
import { DiscoveryModule } from '@nestjs/core';
import {
  SharedWorkflowClientOptions,
  TemporalModuleOptions,
} from './interfaces';
import { TemporalExplorer } from './temporal.explorer';
import {
  ConfigurableModuleClass,
  TEMPORAL_MODULE_ASYNC_OPTIONS_TYPE,
  TEMPORAL_MODULE_OPTIONS_TYPE,
} from './temporal.module-definition';
import { createClientProviders } from './temporal.providers';
import { TemporalMetadataAccessor } from './temporal-metadata.accessors';
import { createClientAsyncProvider } from './utils';

@Module({})
export class TemporalModule extends ConfigurableModuleClass {
  /**
   * Create a new Temporal worker.
   *
   * @deprecated Use registerWorker.
   */
  public static forRoot(options: typeof TEMPORAL_MODULE_OPTIONS_TYPE): DynamicModule {
    return TemporalModule.registerWorker(options);
  }

  /**
   * Create a new Temporal worker.
   *
   * @deprecated Use registerWorker.
   */
  public static forRootAsync(
    options: typeof TEMPORAL_MODULE_ASYNC_OPTIONS_TYPE,
  ): DynamicModule {
    return TemporalModule.registerWorkerAsync(options);
  }

  public static registerWorker(
    options: typeof TEMPORAL_MODULE_OPTIONS_TYPE,
  ): DynamicModule {
    const superDynamicModule = super.registerWorker(options);
    superDynamicModule.imports = [DiscoveryModule];
    superDynamicModule.providers?.push(
      TemporalExplorer,
      TemporalMetadataAccessor,
    );
    return superDynamicModule;
  }

  public static registerWorkerAsync(
    options: typeof TEMPORAL_MODULE_ASYNC_OPTIONS_TYPE,
  ): DynamicModule {
    const superDynamicModule = super.registerWorkerAsync(options);
    superDynamicModule.imports?.push(DiscoveryModule);
    superDynamicModule.providers?.push(
      TemporalExplorer,
      TemporalMetadataAccessor,
    );
    return superDynamicModule;
  }

  public static registerClient(options?: TemporalModuleOptions): DynamicModule {
    const createClientProvider = createClientProviders(options ? [options] : [{}]);
    return {
      global: true,
      module: TemporalModule,
      providers: createClientProvider,
      exports: createClientProvider,
    };
  }

  public static registerClientAsync(
    asyncSharedWorkflowClientOptions: SharedWorkflowClientOptions,
  ): DynamicModule {
    const providers = createClientAsyncProvider(
      asyncSharedWorkflowClientOptions,
    );

    return {
      global: true,
      module: TemporalModule,
      providers,
      exports: providers,
    };
  }
}
