import { Injectable } from '@nestjs/common';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import { GetMailboxTimezoneQuery } from './get-mailbox-timezone.query';

const UTC = 'UTC';

export interface ResolvedMailboxTimezone {
  ianaTimeZone: string;
  outlookTimeZone: string;
  notes: string[];
}

@Injectable()
export class ResolveMailboxTimezoneQuery {
  public constructor(private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery) {}

  public async run(userProfileId: UserProfileTypeID): Promise<ResolvedMailboxTimezone> {
    const mailboxTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const mappedIana =
      mailboxTimeZone === undefined ? undefined : resolveIanaTimezone(mailboxTimeZone);
    if (mailboxTimeZone === undefined) {
      return {
        ianaTimeZone: UTC,
        outlookTimeZone: UTC,
        notes: ['Mailbox timezone was unavailable; times are requested in UTC.'],
      };
    }
    if (mappedIana === undefined) {
      return {
        ianaTimeZone: UTC,
        outlookTimeZone: UTC,
        notes: [
          `Mailbox timezone "${mailboxTimeZone}" could not be mapped to IANA; relative windows are resolved in UTC.`,
        ],
      };
    }
    return {
      ianaTimeZone: mappedIana,
      outlookTimeZone: mailboxTimeZone,
      notes: [],
    };
  }
}
