import { Injectable, Logger } from '@nestjs/common';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

const mailboxTimezoneSchema = z.object({
  timeZone: z.string(),
});

@Injectable()
export class GetMailboxTimezoneQuery {
  private readonly logger = new Logger(GetMailboxTimezoneQuery.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run(userProfileId: UserProfileTypeID): Promise<string | undefined> {
    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId.toString());
      const raw = await client.api('/me/mailboxSettings').select('timeZone').get();
      const parsed = mailboxTimezoneSchema.safeParse(raw);
      if (!parsed.success) {
        this.logger.warn({ msg: 'Unexpected mailboxSettings shape', error: parsed.error });
        return undefined;
      }
      return parsed.data.timeZone;
    } catch (error) {
      this.logger.warn({ msg: 'Failed to fetch mailbox timezone, falling back to UTC', error });
      return undefined;
    }
  }
}
