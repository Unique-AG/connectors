import { Inject, Injectable } from '@nestjs/common';
import { and, asc, eq } from 'drizzle-orm';
import { isNonNull } from 'remeda';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, userProfiles } from '~/db';

interface GetMailboxesInput {
  delegateUserId: string;
  mailbox?: string;
}

@Injectable()
export class GetMailboxesWithFullDelegatedAccessQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(input: GetMailboxesInput): Promise<string[]> {
    const { delegateUserId, mailbox } = input;

    // This query is the same as GetFullDelegatedAccessQuery but it's more efficient because
    // it returns just the mailboxes without the actual directories.
    const rows = await this.db
      .select({ email: userProfiles.email })
      .from(delegatedAccessAccounts)
      .innerJoin(userProfiles, eq(delegatedAccessAccounts.ownerUserId, userProfiles.id))
      .where(
        and(
          eq(delegatedAccessAccounts.delegateUserId, delegateUserId),
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, true),
          ...(mailbox !== undefined ? [eq(userProfiles.email, mailbox)] : []),
        ),
      )
      .orderBy(asc(userProfiles.email));

    return rows.map((r) => r.email).filter(isNonNull);
  }
}
