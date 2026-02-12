import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { DiscoveryService, ModulesContainer, Reflector } from '@nestjs/core';
import { InstanceWrapper } from '@nestjs/core/injector/instance-wrapper';
import { UPTIME_CHECK_METADATA_KEY } from './up.decorator';
import type { IUptimeCheck, UptimeCheckResult, UptimeSummary } from './up.interfaces';

interface RegisteredCheck {
  name: string;
  instance: IUptimeCheck;
}

@Injectable()
export class UpRegistryService implements OnApplicationBootstrap {
  private readonly logger = new Logger(UpRegistryService.name);
  private checks: RegisteredCheck[] = [];

  public constructor(
    private readonly discovery: DiscoveryService,
    private readonly reflector: Reflector,
    private readonly modulesContainer: ModulesContainer,
  ) {}

  public onApplicationBootstrap(): void {
    this.discoverChecks();
  }

  private discoverChecks(): void {
    const modules = Array.from(this.modulesContainer.values());
    const providers = this.discovery.getProviders(undefined, modules);

    for (const wrapper of providers) {
      this.registerProviderIfUptimeCheck(wrapper);
    }

    this.logger.log(`Discovered ${this.checks.length} uptime check(s)`);
  }

  private registerProviderIfUptimeCheck(wrapper: InstanceWrapper): void {
    const instance = wrapper.instance;
    if (!instance || typeof instance !== 'object') return;

    const metatype = wrapper.metatype;
    if (!metatype) return;

    const metadata = this.reflector.get<{ name?: string } | undefined>(
      UPTIME_CHECK_METADATA_KEY,
      metatype,
    );
    if (!metadata) return;

    const checkUp = (instance as IUptimeCheck).checkUp;
    if (typeof checkUp !== 'function') {
      this.logger.warn(
        `Provider ${metatype?.name ?? 'unknown'} has @UptimeCheck but no checkUp() method`,
      );
      return;
    }

    const name = metadata.name ?? metatype?.name ?? 'unknown';
    this.checks.push({ name, instance: instance as IUptimeCheck });
    this.logger.debug(`Registered uptime check: ${name}`);
  }

  public async runAllChecks(): Promise<UptimeSummary> {
    const results = await Promise.all(this.checks.map(async (check) => this.runSingleCheck(check)));

    const status = results.every((r) => r.status === 'up') ? 'up' : 'down';
    const timestamp = new Date().toISOString();

    return {
      status,
      checks: results,
      timestamp,
    };
  }

  private async runSingleCheck(check: RegisteredCheck): Promise<UptimeCheckResult> {
    const start = performance.now();
    try {
      const result = await check.instance.checkUp();
      const durationMs = Math.round((performance.now() - start) * 100) / 100;
      return {
        name: check.name,
        status: result.status,
        message: result.message,
        durationMs,
      };
    } catch (error) {
      const durationMs = Math.round((performance.now() - start) * 100) / 100;
      const message = error instanceof Error ? error.message : String(error);
      return {
        name: check.name,
        status: 'down',
        message,
        durationMs,
      };
    }
  }
}
