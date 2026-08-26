import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, userProfiles } from '~/db';

export interface FullAccessMailboxes {
  /** True when discovery is turned off, so an empty list is a configuration choice, not an answer. */
  scanDisabled: boolean;
  /** Lowercased owner addresses, deduplicated. */
  ownerEmails: string[];
}

/**
 * Mailboxes the delegate holds Exchange Full Access on, addressed by email.
 *
 * Exists alongside GetFullDelegatedAccessQuery rather than reusing it because that query inner-joins
 * `directories`, which holds mail folders. Full Access is a mailbox-wide grant that includes the
 * calendar — verified against live Exchange on 2026-08-26: a delegate holding Full Access on a
 * mailbox whose calendar was never shared still reads GET /users/{owner}/calendars. Joining mail
 * folders would therefore hide a calendar whenever mail sync had not populated the owner yet.
 *
 * Only the address is required, so a missing providerUserId is not disqualifying here the way it is
 * for the mail path — the Graph calendar routes address the mailbox by SMTP.
 */
@Injectable()
export class GetFullAccessMailboxesQuery {
  public constructor(
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(delegateUserProfileId: string): Promise<FullAccessMailboxes> {
    if (this.config.scan === 'disabled') {
      return { scanDisabled: true, ownerEmails: [] };
    }

    const rows = await this.db
      .selectDistinct({ ownerEmail: sql<string>`lower(${userProfiles.email})` })
      .from(delegatedAccessAccounts)
      .innerJoin(userProfiles, eq(delegatedAccessAccounts.ownerUserId, userProfiles.id))
      .where(
        and(
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, true),
          eq(delegatedAccessAccounts.delegateUserId, delegateUserProfileId),
          isNotNull(userProfiles.email),
        ),
      );

    return { scanDisabled: false, ownerEmails: rows.map((row) => row.ownerEmail) };
  }
}
