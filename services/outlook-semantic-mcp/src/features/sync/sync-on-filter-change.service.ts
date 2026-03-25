import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';
import { serializeMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';

@Injectable()
export class SyncOnFilterChangeService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
  ) {}

  public async onModuleInit(): Promise<void> {
    const defaultFilters = serializeMailFilters(this.config.defaultMailFilters);
    this.logger.debug({ msg: `Update all inboxes to new inbox filters`, defaultFilters });

    const maxAttempts = 5;
    const baseDelayMs = 500;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        await this.db.update(inboxConfigurations).set({ filters: defaultFilters }).execute();
        return;
      } catch (err) {
        if (attempt === maxAttempts) {
          this.logger.error({
            msg: 'Failed to update inbox filters after all retries',
            err,
          });
          return;
        }
        const delayMs = baseDelayMs * 2 ** (attempt - 1);
        this.logger.warn({
          msg: `Failed to update inbox filters, retrying`,
          attempt,
          delayMs,
          err,
        });
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }
}
