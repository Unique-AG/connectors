import { Injectable, Logger } from '@nestjs/common';
import { LRUCache } from 'lru-cache';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

const mailboxTimezoneSchema = z.object({
  timeZone: z.string(),
});

const TTL_1_DAY_MS = 1 * 24 * 60 * 60 * 1000;

@Injectable()
export class GetMailboxTimezoneQuery {
  private readonly logger = new Logger(GetMailboxTimezoneQuery.name);
  private readonly cache = new LRUCache<string, string>({ max: 500, ttl: TTL_1_DAY_MS });

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run(userProfileId: UserProfileTypeID): Promise<string | undefined> {
    const key = userProfileId.toString();
    const cached = this.cache.get(key);
    if (cached !== undefined) {
      return cached;
    }

    try {
      const client = this.graphClientFactory.createClientForUser(key);
      const raw = await client.api('/me/mailboxSettings').select('timeZone').get();
      const parsed = mailboxTimezoneSchema.safeParse(raw);
      if (!parsed.success) {
        this.logger.warn({ msg: 'Unexpected mailboxSettings shape', err: parsed.error });
        return undefined;
      }
      this.cache.set(key, parsed.data.timeZone);
      return parsed.data.timeZone;
    } catch (error) {
      this.logger.warn({
        msg: 'Failed to fetch mailbox timezone, falling back to UTC',
        err: error,
      });
      return undefined;
    }
  }
}
