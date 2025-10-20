import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cron, SchedulerRegistry } from '@nestjs/schedule';
import { Client } from 'undici';
import { Config } from '../config';
import { CRON_EVERY_15_MINUTES } from '../constants/defaults.constants';
import { SHAREPOINT_V1_HTTP_CLIENT } from '../http-client.tokens';
import { ClientSecretGraphAuthStrategy } from '../msgraph/auth/client-secret-graph-auth.strategy';
import { OidcGraphAuthStrategy } from '../msgraph/auth/oidc-graph-auth.strategy';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { normalizeError } from '../utils/normalize-error';

@Injectable()
export class SchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly sharepointScanner: SharepointSynchronizationService,
    private readonly schedulerRegistry: SchedulerRegistry,
    @Inject(SHAREPOINT_V1_HTTP_CLIENT) private readonly sharepointV1HttpClient: Client,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.logger.log('SchedulerService initialized with distributed locking');
  }

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    this.tryCallingSharePointApiV1();
    this.runScheduledScan();
  }

  public onModuleDestroy() {
    this.logger.log('SchedulerService is shutting down...');
    this.isShuttingDown = true;
    this.destroyCronJobs();
  }

  @Cron(CRON_EVERY_15_MINUTES)
  public async runScheduledScan(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log('Skipping scheduled scan due to shutdown');
      return;
    }

    try {
      this.logger.log('Scheduler triggered');

      await this.sharepointScanner.synchronize();

      this.logger.log('SharePoint scan completed successfully.');
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error(
        `An unexpected error occurred during the scheduled scan: ${normalizedError.message}`,
      );
    }
  }

  private destroyCronJobs() {
    try {
      const jobs = this.schedulerRegistry.getCronJobs();
      jobs.forEach((job, jobName) => {
        this.logger.log(`Stopping cron job: ${jobName}`);
        job.stop();
      });
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error(`Error stopping cron jobs: ${normalizedError.message}`);
    }
  }

  // Temporary method to test on QA whether token issued via OIDC are eligible to access Sharepoint REST V1 API.
  private async tryCallingSharePointApiV1(): Promise<void> {
    const useOidc = this.configService.get('sharepoint.graphUseOidcAuth', { infer: true });

    const scope = 'https://uniqueapp.sharepoint.com/.default';
    const newAccessToken = await (useOidc
      ? new OidcGraphAuthStrategy(this.configService)
      : new ClientSecretGraphAuthStrategy(this.configService)
    ).getAccessToken(scope);

    const { statusCode, body } = await this.sharepointV1HttpClient.request({
      method: 'GET',
      path: '/sites/UniqueAG/_api/web/sitegroups',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${newAccessToken}`,
      },
    });

    if (200 <= statusCode && statusCode < 300) {
      const bodyData = await body.text();
      this.logger.log(
        `SharePoint API v1 called successfully. Status code: ${statusCode}, Response length: ${bodyData.length}`,
      );
    } else {
      this.logger.error(
        `Error calling SharePoint API V1. Status code: ${statusCode}, Body: ${await body.text()}`,
      );
    }
  }
}
