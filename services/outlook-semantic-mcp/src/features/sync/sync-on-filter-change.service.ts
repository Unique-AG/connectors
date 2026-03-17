import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
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
    await this.db.update(inboxConfiguration).set({ filters: defaultFilters }).execute();
  }
}
