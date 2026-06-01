import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { isNullish } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  delegatedAccessDirectories,
  userProfiles,
} from '~/db';

@Injectable()
export class RemoveDelegatedAccessCommand {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(input: {
    delegateUserId: string;
    ownerEmail: string;
    where: { msGraphDirectoryId: string } | { fullAccess: boolean };
  }): Promise<void> {
    const { delegateUserId, ownerEmail } = input;

    const [ownerProfile] = await this.db
      .select({ id: userProfiles.id })
      .from(userProfiles)
      .where(eq(userProfiles.email, ownerEmail));

    if (!ownerProfile) {
      return;
    }

    const accoutsRow = await this.db.query.delegatedAccessAccounts.findFirst({
      where: and(
        eq(delegatedAccessAccounts.delegateUserId, delegateUserId),
        eq(delegatedAccessAccounts.ownerUserId, ownerProfile.id),
      ),
    });

    if (isNullish(accoutsRow)) {
      return;
    }

    if ('fullAccess' in input.where) {
      await this.db
        .update(delegatedAccessAccounts)
        .set({ hasFullDelegatedAccess: false })
        .where(and(eq(delegatedAccessAccounts.id, accoutsRow.id)));
      return;
    }
    const msGraphDirectoryId = input.where.msGraphDirectoryId;
    assert.ok(
      msGraphDirectoryId,
      `Missing directory id for delegated access removal delegateUserId:${input.delegateUserId}, ownerUserId:${ownerProfile.id}`,
    );

    await this.db
      .delete(delegatedAccessDirectories)
      .where(
        and(
          eq(delegatedAccessDirectories.accountsId, accoutsRow.id),
          eq(delegatedAccessDirectories.directoryId, msGraphDirectoryId),
        ),
      );
  }
}
