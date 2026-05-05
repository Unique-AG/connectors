import { Inject, Injectable } from '@nestjs/common';
import { and, asc, eq } from 'drizzle-orm';
import { isNonNull } from 'remeda';
import { DRIZZLE, DrizzleDatabase, delegatedAccessPipelines, userProfiles } from '~/db';

interface GetMailboxesInput {
  delegateUserId: string;
  mailbox?: string;
}

@Injectable()
export class GetMailboxesWithFullDelegatedAccessQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(input: GetMailboxesInput): Promise<string[]> {
    const { delegateUserId, mailbox } = input;

    const rows = await this.db
      .select({ email: userProfiles.email })
      .from(delegatedAccessPipelines)
      .innerJoin(userProfiles, eq(delegatedAccessPipelines.ownerUserId, userProfiles.id))
      .where(
        and(
          eq(delegatedAccessPipelines.delegateUserId, delegateUserId),
          eq(delegatedAccessPipelines.hasFullDelegatedAccess, true),
          ...(mailbox !== undefined ? [eq(userProfiles.email, mailbox)] : []),
        ),
      )
      .orderBy(asc(userProfiles.email));

    return rows.map((r) => r.email).filter(isNonNull);
  }
}
