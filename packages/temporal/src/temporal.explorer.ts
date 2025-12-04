import {
  Inject,
  Injectable,
  Logger,
  OnApplicationBootstrap,
  OnModuleDestroy,
  OnModuleInit,
} from '@nestjs/common';
import { DiscoveryService, MetadataScanner } from '@nestjs/core';
import { InstanceWrapper } from '@nestjs/core/injector/instance-wrapper';
import {
  NativeConnection,
  NativeConnectionOptions,
  Runtime,
  RuntimeOptions,
  Worker,
  WorkerOptions,
} from '@temporalio/worker';
import { TEMPORAL_MODULE_OPTIONS_TOKEN, TemporalModuleOptions } from './temporal.module-definition';
import { TemporalMetadataAccessor } from './temporal-metadata.accessors';

@Injectable()
export class TemporalExplorer implements OnModuleInit, OnModuleDestroy, OnApplicationBootstrap {
  private readonly logger = new Logger(TemporalExplorer.name);
  private worker?: Worker;
  private workerRunPromise?: Promise<void>;

  public constructor(
    private readonly discoveryService: DiscoveryService,
    private readonly metadataAccessor: TemporalMetadataAccessor,
    private readonly metadataScanner: MetadataScanner,
    @Inject(TEMPORAL_MODULE_OPTIONS_TOKEN) private readonly options: TemporalModuleOptions,
  ) {}

  public async onModuleInit() {
    await this.explore();
  }

  public async onModuleDestroy() {
    try {
      this.worker?.shutdown();
      await this.workerRunPromise;
    } catch (err: unknown) {
      this.logger.warn('Temporal worker was not cleanly shutdown.', { err });
    }
  }

  public onApplicationBootstrap() {
    this.workerRunPromise = this.worker?.run();
  }

  public async explore() {
    const workerConfig = this.getWorkerConfigOptions();
    const runTimeOptions = this.getRuntimeOptions();
    const connectionOptions = this.getNativeConnectionOptions();

    // should contain taskQueue
    if (workerConfig.taskQueue) {
      this.findDuplicateActivityMethods();

      const activitiesFunc = await this.handleActivities();

      if (runTimeOptions) {
        this.logger.verbose('Instantiating a new Core object');
        Runtime.install(runTimeOptions);
      }

      const workerOptions = {
        activities: activitiesFunc,
      } as WorkerOptions;
      if (connectionOptions) {
        this.logger.verbose('Connecting to the Temporal server');
        workerOptions.connection = await NativeConnection.connect(connectionOptions);
      }

      this.logger.verbose('Creating a new Worker');
      this.worker = await Worker.create(Object.assign(workerOptions, workerConfig));
    }
  }

  public getWorkerConfigOptions(): WorkerOptions {
    return this.options.workerOptions;
  }

  public getNativeConnectionOptions(): NativeConnectionOptions | undefined {
    return this.options.connectionOptions;
  }

  public getRuntimeOptions(): RuntimeOptions | undefined {
    return this.options.runtimeOptions;
  }

  public getActivityClasses(): object[] | undefined {
    return this.options.activityClasses;
  }

  public findDuplicateActivityMethods() {
    if (!this.options.errorOnDuplicateActivities) {
      return;
    }

    const activityClasses = this.getActivityClasses();
    const activityMethods: Record<string, string[]> = {};

    activityClasses?.forEach((wrapper) => {
      const { instance } = wrapper as InstanceWrapper;

      this.metadataScanner.getAllMethodNames(Object.getPrototypeOf(instance)).map((key) => {
        if (this.metadataAccessor.isActivity(instance[key])) {
          activityMethods[key] = (activityMethods[key] || []).concat(instance.constructor.name);
        }
        return key;
      });
    });

    const violations = Object.entries(activityMethods).filter(
      ([_method, classes]) => classes.length > 1,
    );

    if (violations.length > 0) {
      const message = `Activity names must be unique across all Activity classes. Identified activities with conflicting names: ${JSON.stringify(
        Object.fromEntries(violations),
      )}`;
      this.logger.error(message);
      throw new Error(message);
    }
  }

  public async handleActivities() {
    const activitiesMethod: Record<string, () => void> = {};

    const activityClasses = this.getActivityClasses();
    const activities: InstanceWrapper[] = this.discoveryService
      .getProviders()
      .filter(
        (wrapper: InstanceWrapper) =>
          this.metadataAccessor.isActivities(
            !wrapper.metatype || wrapper.inject ? wrapper.instance?.constructor : wrapper.metatype,
          ) &&
          (!activityClasses || (wrapper.metatype && activityClasses.includes(wrapper.metatype))),
      );

    activities.forEach((wrapper: InstanceWrapper) => {
      const { instance } = wrapper;
      const isRequestScoped = !wrapper.isDependencyTreeStatic();

      this.metadataScanner.scanFromPrototype(
        instance,
        Object.getPrototypeOf(instance),
        async (key: string) => {
          if (this.metadataAccessor.isActivity(instance[key])) {
            if (isRequestScoped) {
              // TODO: handle request scoped
            } else {
              activitiesMethod[key] = instance[key].bind(instance);
            }
          }
        },
      );
    });

    return activitiesMethod;
  }
}
