import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, delegatedAccessPipelines, userProfiles } from '~/db';

@Injectable()
export class MarkPipelineNoFullAccessCommand {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(input: { delegateUserId: string; ownerEmail: string }): Promise<void> {
    const { delegateUserId, ownerEmail } = input;

    const [ownerProfile] = await this.db
      .select({ id: userProfiles.id })
      .from(userProfiles)
      .where(eq(userProfiles.email, ownerEmail));

    if (!ownerProfile) {
      return;
    }

    await this.db
      .update(delegatedAccessPipelines)
      .set({ hasFullDelegatedAccess: false })
      .where(
        and(
          eq(delegatedAccessPipelines.delegateUserId, delegateUserId),
          eq(delegatedAccessPipelines.ownerUserId, ownerProfile.id),
        ),
      );
  }
}
